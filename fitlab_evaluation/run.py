"""Explicit live evaluation; stop before any request when resource checks fail."""
import argparse
from .artifacts import BoundedParser
import hashlib
import json
import os
import math
import statistics
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .grader import grade, load_pack
from .lemonade import IntegrationError, LemonadeClient, MODEL, windows_memory, require_resources, validate_health, validate_result, validate_memory
from .artifacts import source_digest,digest,stable_json
from fitlab_foundation.planner_cli import _read_bounded_document, run_document
from fitlab_foundation.serialization import to_primitive

ROOT = Path(__file__).resolve().parents[1]


def identity():
    # Canonical line-ending-independent digests: git blob bytes and worktree
    # bytes must agree, including on a CRLF Windows checkout.
    paths = sorted(p for folder in ('fitlab_foundation','fitlab_evaluation','fixtures')
                   for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return {str(p.relative_to(ROOT)).replace('\\','/'): source_digest(p.read_bytes()) for p in paths}


def evaluate(plan_document, repeats, *, client, memory, pause=time.sleep, budget_seconds=600, checkpoint=None, execution_kind='SYNTHETIC_TEST'):
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError('repeats must be 1..3')
    if type(budget_seconds) not in (int,float) or not 0 < budget_seconds <= 600 or not math.isfinite(budget_seconds):
        raise ValueError('session budget must be finite and within 0..600 seconds')
    if type(client.timeout) not in (int,float) or not 0 < client.timeout <= 60 or not math.isfinite(client.timeout):
        raise ValueError('invalid adapter timeout')
    if execution_kind not in {'SYNTHETIC_TEST','LOCAL_RUNTIME'} or (execution_kind=='LOCAL_RUNTIME' and type(client) is not LemonadeClient):
        raise ValueError('invalid execution kind or runtime adapter')
    pack, pack_hash = load_pack(ROOT/'fixtures/tasks-v2.json')
    plan = None if plan_document is None else to_primitive(run_document(plan_document))
    if plan_document is not None and any(s['model']['model_id'] != MODEL for s in plan_document['scenarios']):
        raise ValueError('all planning scenarios must name the evaluated model')
    record = {'schema_version':'fitlab-evaluation-v2','execution_kind':execution_kind,'run_id':str(uuid.uuid4()),
              'started_at':datetime.now(timezone.utc).isoformat(),'source_sha256':identity(),
              'task_pack_sha256':pack_hash,'requested_repeats':repeats,'model':MODEL,
              'planning_input':plan_document,'planning_output':plan,
              'planning_status':'UNAVAILABLE' if plan is None else 'CALCULATED_FROM_DECLARATIONS',
              'planning_provenance':('No planning metadata supplied; task-only run does not establish hardware fit or either planning journey.' if plan is None else 'Owner-declared model/workload metadata; not inferred from measured task performance.'),
              'rows':[],'status':'NOT_STARTED','resource_samples':[],
              'protocol':{'id':'fitlab-f5-v1','warmup_requests':0,'order':'round-major, frozen case order',
                          'concurrency':1,'pause_seconds':1,'session_budget_seconds':budget_seconds,
                          'request_timeout_seconds':client.timeout,'cold_load_measured':False,
                          'first_request_label':'first observed request; already-loaded model, cache state unknown'},
              'limitations':['Known toy tasks, not held-out general capability evidence.',
                             'No TTFT or decode throughput measured.',
                             'Physical memory snapshots are not process peak RAM or attributable model RAM.',
                             'No model download, load, switch or server startup performed.']}
    def save():
        if checkpoint is not None:
            checkpoint(record)
    started=time.monotonic()
    record['status']='RUNNING'
    save()
    try:
        for repeat in range(repeats):
            for case in pack['cases']:
                if time.monotonic()-started+2*client.timeout+1 > budget_seconds:
                    raise IntegrationError('session time budget exhausted')
                snapshot=validate_memory(memory()); record['resource_samples'].append(snapshot); require_resources(snapshot)
                health=validate_health(client.ready())
                if 'runtime' not in record: record['runtime']=health
                if time.monotonic()-started+client.timeout+1 > budget_seconds:
                    raise IntegrationError('session time budget exhausted after health check')
                snapshot=validate_memory(memory());record['resource_samples'].append(snapshot);require_resources(snapshot)
                row={'case_id':case['id'],'repeat':repeat+1,'status':'STARTED','runtime':health,
                     'started_at':datetime.now(timezone.utc).isoformat(),
                     'sequence_label':'first_observed_request' if not record['rows'] else 'subsequent_request'}
                record['rows'].append(row)
                save()
                try:
                    result=validate_result(client.complete(case['prompt']),case['prompt'])
                    row.update(result)
                    row['response_sha256']=digest(stable_json(result['response']).encode('utf-8'))
                    choice=result['response']['choices'][0]; message=choice['message']
                    row['grade']=grade(case,message.get('content'),tool_calls=message.get('tool_calls'),
                                       function_call=message.get('function_call'),refusal=message.get('refusal'),
                                       finish_reason=choice.get('finish_reason'))
                    row['status']='MEASURED'
                    row['completed_at']=datetime.now(timezone.utc).isoformat()
                    after=validate_memory(memory());record['resource_samples'].append(after);require_resources(after)
                except Exception as exc:
                    row['error']=str(exc)[:512] if isinstance(exc,IntegrationError) else 'adapter failure: '+type(exc).__name__
                    if row['status']!='MEASURED': row['status']='FAILED'
                    raise
                save()
                pause(1)
        record['status']='COMPLETED'
    except Exception as exc:
        record['status']='STOPPED';record['stop_reason']=str(exc)[:512] if isinstance(exc,IntegrationError) else 'evaluation failure: '+type(exc).__name__
    except KeyboardInterrupt:
        record['status']='INTERRUPTED'
    measured=[r for r in record['rows'] if r['status']=='MEASURED']
    record['summary']={'planned_count':len(pack['cases'])*repeats,'measured_count':len(measured),
                       'passed_count':sum(r['grade']['passed'] for r in measured),
                       'failed_or_unrun_count':len(pack['cases'])*repeats-sum(r['grade']['passed'] for r in measured),
                       'median_client_latency_seconds':statistics.median(r['elapsed_seconds'] for r in measured) if measured else None}
    record['summary']['by_case'] = {}
    for case in pack['cases']:
        rows=[r for r in measured if r['case_id']==case['id']]
        passed=sum(r['grade']['passed'] for r in rows)
        record['summary']['by_case'][case['id']]={
            'planned_count':repeats,'measured_count':len(rows),'passed_count':passed,
            'failed_or_unrun_count':repeats-passed,
            'median_client_latency_seconds':statistics.median(r['elapsed_seconds'] for r in rows) if rows else None}
    record['completed_at']=datetime.now(timezone.utc).isoformat()
    save()
    return record


def main():
    parser=BoundedParser(description=__doc__)
    parser.add_argument('--plan',type=Path,help='Optional sourced planning input; omit for task-only measurements')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,choices=(1,2,3),default=3)
    args=parser.parse_args()
    # Offline/no-fetch guard, identical to workflow.execute's contract: this
    # entry point can issue LOCAL_RUNTIME inference, so it refuses unless a
    # prepared, offline, telemetry-disabled runtime contract is observable.
    # Refusal happens before any evidence path is created.
    from .artifacts import ArtifactError
    # Late import: workflow imports this module (evaluate, identity), so the
    # config seam is fetched at call time. Tests patch
    # fitlab_evaluation.workflow.safe_runtime_config.
    from .workflow import safe_runtime_config
    observed=safe_runtime_config()
    from .grader import exact_equal
    if not exact_equal(observed,{'offline':True,'no_fetch_executables':True}):
        print(stable_json({'status':'ERROR','code':'RUNTIME_NOT_PROVEN_OFFLINE'}),end='',file=sys.stderr)
        return 2
    # Reserve a new evidence path before any inference; never overwrite past trials.
    # newline='' keeps the placeholder byte-stable across platforms.
    with args.output.open('x',encoding='utf-8',newline='') as output:
        output.write('{"status":"RESERVED","inference_requests":0}\n')
    def checkpoint(record):
        # Replace only our reserved output, preserving the last complete snapshot on interruption.
        temporary = None
        try:
            # newline='' keeps JSONL/JSON bytes platform-stable (sealed-evidence contract).
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='',dir=args.output.parent,
                                             prefix=args.output.name+'.',suffix='.tmp',delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(record,handle,indent=2,ensure_ascii=True,allow_nan=False)
                handle.write('\n');handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,args.output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    try:
        document=None if args.plan is None else _read_bounded_document(args.plan)
        if document is not None:
            run_document(document)
        load_pack(ROOT/'fixtures/tasks-v2.json')
        if document is not None and any(s['model']['model_id'] != MODEL for s in document['scenarios']):
            raise ValueError('planning model mismatch')
    except (ValueError,OSError) as exc:
        result={'schema_version':'fitlab-evaluation-v1','status':'INVALID_INPUT',
                'error':type(exc).__name__,'rows':[],'inference_requests':0}
        checkpoint(result)
    else:
        result=evaluate(document,args.repeats,client=LemonadeClient(),
                        memory=windows_memory,checkpoint=checkpoint,execution_kind='LOCAL_RUNTIME')
    return 0 if result['status']=='COMPLETED' else 2

def cli():
    try:
        return main()
    except FileExistsError:
        code='OUTPUT_EXISTS'
    except OSError:
        code='IO_ERROR'
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,UnicodeError):
        code='INVALID_INPUT'
    import sys
    print(json.dumps({'status':'ERROR','code':code},sort_keys=True),file=sys.stderr)
    return 2

if __name__=='__main__': raise SystemExit(cli())
