"""Strict reload/recomputation against a separately frozen source trust snapshot.

Hash consistency does not authenticate a model or a machine. Runtime origin is a
recorded declaration and must also be corroborated by independent live review.
"""
import hashlib
import json
import math
import re
import statistics
import subprocess
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from .artifacts import ArtifactError,stable_json,digest,source_digest,load_json
from .grader import strict_json,grade,exact_equal
from .lemonade import MODEL,validate_health,validate_result,validate_memory,require_resources,IntegrationError
from fitlab_foundation.planner_cli import run_document
from fitlab_foundation.serialization import to_primitive

ROOT=Path(__file__).resolve().parents[1]
HASH=re.compile(r'^[0-9a-f]{64}$')


def reject(code):raise ArtifactError(code)


def make_trust(commit='HEAD'):
    # The commit argument reaches a git subprocess. It must be a plain
    # revision name: no leading dash (which git would read as an option), no
    # whitespace, no control or NUL characters, and no path separators.
    if type(commit) is not str or not commit or len(commit) > 255:
        reject('INVALID_SOURCE')
    if commit.startswith('-') or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in commit):
        reject('INVALID_SOURCE')
    if '/' in commit and not commit.startswith('refs/'):
        reject('INVALID_SOURCE')
    if commit.startswith('refs/'):
        if not re.fullmatch(r'refs/(heads|tags)/[A-Za-z0-9._/-]{1,200}', commit):
            reject('INVALID_SOURCE')
    elif not re.fullmatch(r'[A-Za-z0-9._~^@-]{1,64}', commit):
        reject('INVALID_SOURCE')

    def git(*args):
        try:return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.DEVNULL,timeout=15)
        except (OSError,subprocess.SubprocessError) as exc:raise ArtifactError('SOURCE_UNAVAILABLE') from exc
    try:
        revision=git('rev-parse','--verify',commit+'^{commit}').decode().strip()
    except ArtifactError:raise
    if not re.fullmatch('[0-9a-f]{40}',revision):reject('INVALID_SOURCE')
    tree=git('rev-parse',revision+'^{tree}').decode().strip()
    names=git('ls-tree','-r','--name-only',revision,'--','fitlab_foundation','fitlab_evaluation','fixtures').decode().splitlines()
    files={p:source_digest(git('show',revision+':'+p)) for p in names if '__pycache__' not in p.split('/')}
    pack=git('show',revision+':fixtures/tasks-v2.json').decode('utf-8')
    return {'schema_version':'fitlab-trust-v1','source_commit':revision,'source_tree':tree,
            'source_sha256':files,'task_pack_text':pack,'task_pack_sha256':source_digest(pack.encode()),
            'boundary':'Trusted separately from a result file; hashes are integrity checks, not proof of execution origin.'}


def trust_from_package_index(root=ROOT):
    """Reconstruct exact source trust from a verified package index."""
    root=Path(root)
    index,_=load_json(root/'PACKAGE_INDEX.json')
    required={'schema_version','source_commit','source_tree','members'}
    if type(index) is not dict or not required<=index.keys() or index['schema_version']!='fitlab-review-package-v2':
        reject('INVALID_PACKAGE_INDEX')
    for key in ('source_commit','source_tree'):
        if type(index[key]) is not str or not re.fullmatch('[0-9a-f]{40}',index[key]):
            reject('INVALID_PACKAGE_INDEX')
    records=index['members']
    if type(records) is not list or not records or len(records)>4096:
        reject('INVALID_PACKAGE_INDEX')
    all_files={}
    for record in records:
        if type(record) is not dict or set(record)!={'path','bytes','sha256'}:
            reject('INVALID_PACKAGE_INDEX')
        relative=record['path']; expected=record['sha256']; size=record['bytes']
        if (type(relative) is not str or not relative or '\\' in relative or relative.startswith('/')
                or '..' in relative.split('/') or relative in all_files or type(size) is not int or size<0
                or type(expected) is not str or not HASH.fullmatch(expected)):
            reject('INVALID_PACKAGE_INDEX')
        try:data=(root/relative).read_bytes()
        except OSError:reject('SOURCE_SNAPSHOT_MISMATCH')
        if len(data)!=size or digest(data)!=expected:
            reject('SOURCE_SNAPSHOT_MISMATCH')
        all_files[relative]=source_digest(data)
    source_files={p:h for p,h in all_files.items() if p.startswith(('fitlab_foundation/','fitlab_evaluation/','fixtures/')) and '__pycache__' not in p.split('/')}
    try:pack=(root/'fixtures/tasks-v2.json').read_text(encoding='utf-8')
    except (OSError,UnicodeDecodeError):reject('INVALID_TASK_PACK')
    pack_hash=source_digest(pack.encode())
    if source_files.get('fixtures/tasks-v2.json')!=pack_hash:
        reject('TASK_HASH_MISMATCH')
    return {'schema_version':'fitlab-trust-v1','source_commit':index['source_commit'],'source_tree':index['source_tree'],
            'source_sha256':source_files,'task_pack_text':pack,'task_pack_sha256':pack_hash,
            'boundary':'Reconstructed from exact package index; hashes are integrity checks, not proof of execution origin.'}


@lru_cache(maxsize=8)
def _committed_trust(commit):
    return make_trust(commit)


def source_binding():
    return "LOCAL_GIT_VERIFIED" if (ROOT/".git").exists() else "EXTERNALLY_SUPPLIED_SNAPSHOT"


def validate_trust(trust):
    try:return _validate_trust(trust)
    except ArtifactError:raise
    except Exception as exc:raise ArtifactError("INVALID_TRUST") from exc


def _validate_trust(trust):
    required={'schema_version','source_commit','source_tree','source_sha256','task_pack_text','task_pack_sha256','boundary'}
    if type(trust) is not dict or set(trust)!=required or trust['schema_version']!='fitlab-trust-v1':reject('INVALID_TRUST')
    for k in ('source_commit','source_tree'):
        if type(trust[k]) is not str or not re.fullmatch('[0-9a-f]{40}',trust[k]):reject('INVALID_TRUST')
    files=trust['source_sha256']
    if type(files) is not dict or not files or any(type(k) is not str or type(v) is not str or not HASH.fullmatch(v) for k,v in files.items()):reject('INVALID_TRUST')
    if not {'fitlab_evaluation/run.py','fitlab_evaluation/lemonade.py'}<=files.keys():reject('INCOMPLETE_SOURCE_IDENTITY')
    if any('\\' in p or p.startswith('/') or '..' in p.split('/') for p in files):reject('INVALID_TRUST')
    if (ROOT/'.git').exists():
        frozen=_committed_trust(trust['source_commit'])
        if not exact_equal(trust,frozen):reject('SOURCE_COMMIT_MISMATCH')
    else:
        for relative, expected in files.items():
            path=ROOT/relative
            try:actual=source_digest(path.read_bytes())
            except OSError:reject('SOURCE_SNAPSHOT_MISMATCH')
            if actual!=expected:reject('SOURCE_SNAPSHOT_MISMATCH')
    if type(trust['task_pack_text']) is not str or len(trust['task_pack_text'])>65536:reject('INVALID_TRUST')
    if source_digest(trust['task_pack_text'].encode())!=trust['task_pack_sha256'] or files.get('fixtures/tasks-v2.json')!=trust['task_pack_sha256']:reject('TASK_HASH_MISMATCH')
    # Current verifier may replay only the accepted grader and preserved planner.
    for p in ('fitlab_evaluation/grader.py','fitlab_foundation/planner.py','fitlab_foundation/planner_cli.py',
              'fitlab_foundation/contracts.py','fitlab_foundation/requirements.py','fitlab_foundation/arithmetic.py',
              'fitlab_foundation/serialization.py','fitlab_foundation/units.py','fitlab_foundation/validation.py'):
        if files.get(p)!=source_digest((ROOT/p).read_bytes()):reject('UNSUPPORTED_REPLAY_VERSION')
    try:pack=strict_json(trust['task_pack_text'])
    except (ValueError,RecursionError):reject('INVALID_TASK_PACK')
    if pack.get('schema_version')!='fitlab-tasks-v2' or [c.get('id') for c in pack.get('cases',[])]!=['E1','E2','E3','D1','D2','D3','D4','D5']:reject('INVALID_TASK_PACK')
    # A trust file cannot silently substitute easier expected answers.
    if trust['task_pack_sha256']!=source_digest((ROOT/'fixtures/tasks-v2.json').read_bytes()):reject('UNSUPPORTED_TASK_PACK')
    return pack


def _time(value):
    if type(value) is not str or len(value)>64:reject('INVALID_TIMESTAMP')
    try:t=datetime.fromisoformat(value)
    except ValueError:reject('INVALID_TIMESTAMP')
    if t.tzinfo is None:reject('INVALID_TIMESTAMP')
    return t


def summarize(rows,cases,repeats):
    measured=[r for r in rows if r['status']=='MEASURED']
    def counts(items,planned):
        passed=sum(r['grade']['passed'] for r in items)
        return {'planned_count':planned,'measured_count':len(items),'passed_count':passed,
                'failed_or_unrun_count':planned-passed,
                'median_client_latency_seconds':statistics.median(r['elapsed_seconds'] for r in items) if items else None}
    result=counts(measured,len(cases)*repeats)
    result['by_case']={c['id']:counts([r for r in measured if r['case_id']==c['id']],repeats) for c in cases}
    return result


def verify_record(record,trust):
    pack=validate_trust(trust)
    try:return _verify(record,trust,pack)
    except ArtifactError:raise
    except Exception as exc:raise ArtifactError('INVALID_EVALUATION') from exc


def _verify(r,trust,pack):
    required={'schema_version','execution_kind','run_id','started_at','source_sha256','task_pack_sha256','requested_repeats','model','planning_input','planning_output','planning_status','planning_provenance','rows','status','resource_samples','protocol','limitations'}
    optional={'runtime','stop_reason','completed_at','summary'}
    if type(r) is not dict or not required<=r.keys() or r.keys()-required-optional:reject('INVALID_EVALUATION')
    if r['schema_version']!='fitlab-evaluation-v2' or r['execution_kind'] not in ('LOCAL_RUNTIME','SYNTHETIC_TEST') or r['model']!=MODEL:reject('UNSUPPORTED_EVALUATION')
    if type(r['run_id']) is not str or str(uuid.UUID(r['run_id']))!=r['run_id']:reject('INVALID_RUN_ID')
    started=_time(r['started_at'])
    completed=None if 'completed_at' not in r else _time(r['completed_at'])
    if completed is not None and completed<started:reject('INVALID_TIMESTAMP_ORDER')
    # Cross-platform source separators normalize only to the known relative paths.
    sources=r['source_sha256']
    if type(sources) is not dict:reject('SOURCE_MISMATCH')
    normalized={k.replace('\\','/'):v for k,v in sources.items()}
    if len(normalized)!=len(sources) or not exact_equal(normalized,trust['source_sha256']):reject('SOURCE_MISMATCH')
    if r['task_pack_sha256']!=trust['task_pack_sha256']:reject('TASK_HASH_MISMATCH')
    repeats=r['requested_repeats']
    if type(repeats) is not int or not 1<=repeats<=3:reject('INVALID_REPETITIONS')
    expected_protocol={'id':'fitlab-f5-v1','warmup_requests':0,'order':'round-major, frozen case order','concurrency':1,'pause_seconds':1,'cold_load_measured':False,
                       'first_request_label':'first observed request; already-loaded model, cache state unknown'}
    protocol=r['protocol']
    if type(protocol) is not dict or set(protocol)!=set(expected_protocol)|{'session_budget_seconds','request_timeout_seconds'}:reject('INVALID_PROTOCOL')
    if not all(exact_equal(protocol[k],v) for k,v in expected_protocol.items()):reject('INVALID_PROTOCOL')
    for k,limit in (('session_budget_seconds',600),('request_timeout_seconds',60)):
        v=protocol[k]
        if type(v) not in (int,float) or not 0<v<=limit or not math.isfinite(v):reject('INVALID_PROTOCOL')
    if r['planning_input'] is None:
        if r['planning_output'] is not None or r['planning_status']!='UNAVAILABLE':reject('PLANNING_MISMATCH')
    else:
        if r['planning_status']!='CALCULATED_FROM_DECLARATIONS':reject('PLANNING_MISMATCH')
        actual=to_primitive(run_document(r['planning_input']))
        if not exact_equal(actual,r['planning_output']):reject('PLANNING_MISMATCH')
        if any(s['model']['model_id']!=MODEL for s in r['planning_input']['scenarios']):reject('PLANNING_MISMATCH')
    if type(r['resource_samples']) is not list or len(r['resource_samples'])>72:reject('INVALID_RESOURCES')
    for sample in r['resource_samples']:validate_memory(sample)
    if 'runtime' in r:validate_health(r['runtime'])
    cases=pack['cases'];sequence=[(c,n) for n in range(1,repeats+1) for c in cases]
    rows=r['rows']
    if type(rows) is not list or len(rows)>len(sequence):reject('INVALID_ROWS')
    previous=started
    sample_index=0
    elapsed_total=0.0
    for index,row in enumerate(rows):
        case,n=sequence[index]
        if elapsed_total+index*protocol['pause_seconds']+2*protocol['request_timeout_seconds']+1>protocol['session_budget_seconds']:reject('IMPOSSIBLE_SESSION_BUDGET')
        base={'case_id','repeat','status','runtime','started_at','sequence_label'}
        allowed=base|{'request','response','response_sha256','elapsed_seconds','timing_kind','grade','completed_at','error'}
        if type(row) is not dict or not base<=row.keys() or row.keys()-allowed:reject('INVALID_ROW')
        if not exact_equal(row['repeat'],n) or row['case_id']!=case['id']:reject('ROW_IDENTITY_MISMATCH')
        if row['sequence_label']!=('first_observed_request' if index==0 else 'subsequent_request'):reject('ROW_IDENTITY_MISMATCH')
        rowstart=_time(row['started_at'])
        if rowstart<previous or (completed is not None and rowstart>completed):reject('INVALID_TIMESTAMP_ORDER')
        if r['execution_kind']=='LOCAL_RUNTIME' and index>0 and (rowstart-previous).total_seconds()<protocol['pause_seconds']-0.05:reject('MISSING_INTER_REQUEST_PAUSE')
        previous=rowstart
        # The producer samples before health, before inference, then after completion.
        samples=r['resource_samples']
        if len(samples)<sample_index+2:reject('MISSING_RESOURCE_EVIDENCE')
        for sample in samples[sample_index:sample_index+2]:
            try:require_resources(sample)
            except IntegrationError:reject('PRE_REQUEST_RESOURCE_GATE_FAILED')
        sample_index+=2
        if 'error' in row and (index!=len(rows)-1 or r['status']!='STOPPED' or type(row['error']) is not str or not 0<len(row['error'])<=512):reject('INVALID_ROW_ERROR')
        validate_health(row['runtime'])
        status=row['status']
        if status=='MEASURED':
            expected_response_hash=digest(stable_json(row.get('response')).encode('utf-8'))
            if type(row.get('response_sha256')) is not str or not HASH.fullmatch(row['response_sha256']) or row['response_sha256']!=expected_response_hash:
                reject('RESPONSE_HASH_MISMATCH')
            result={k:row[k] for k in ('request','response','elapsed_seconds','timing_kind') if k in row}
            validate_result(result,case['prompt'])
            rowend=_time(row['completed_at'])
            if rowend<rowstart or (completed is not None and rowend>completed):reject('INVALID_TIMESTAMP_ORDER')
            elapsed=row['elapsed_seconds']
            elapsed_total+=elapsed
            # UTC timestamps may be coarser than monotonic client timing on Windows.
            if elapsed>protocol['request_timeout_seconds'] or elapsed>(rowend-rowstart).total_seconds()+0.05 or elapsed_total>protocol['session_budget_seconds']:reject('INCONSISTENT_TIMING')
            previous=rowend
            if sample_index<len(samples):
                try:require_resources(samples[sample_index])
                except IntegrationError:
                    if not (r['status']=='STOPPED' and index==len(rows)-1 and 'error' in row):reject('POST_REQUEST_RESOURCE_GATE_FAILED')
                sample_index+=1
            elif not (r['status']=='STOPPED' and index==len(rows)-1 and 'error' in row):reject('MISSING_RESOURCE_EVIDENCE')
            choice=row['response']['choices'][0];message=choice['message']
            expected=grade(case,message['content'],tool_calls=message.get('tool_calls'),function_call=message.get('function_call'),refusal=message.get('refusal'),finish_reason=choice.get('finish_reason'))
            if not exact_equal(row.get('grade'),expected):reject('GRADE_MISMATCH')
        elif status in ('FAILED','STARTED'):
            if index!=len(rows)-1 or 'grade' in row:reject('INVALID_PARTIAL_ROW')
            if set(row)-base-{'error'}:reject('INVALID_PARTIAL_ROW')
            if status=='FAILED' and (type(row.get('error')) is not str or not row['error']):reject('INVALID_PARTIAL_ROW')
        else:reject('INVALID_ROW_STATUS')
    status=r['status']
    if status not in ('RUNNING','COMPLETED','STOPPED','INTERRUPTED'):reject('INVALID_RUN_STATUS')
    if status=='COMPLETED' and (len(rows)!=len(sequence) or any(row['status']!='MEASURED' for row in rows)):reject('FALSE_COMPLETION')
    if status=='STOPPED' and (type(r.get('stop_reason')) is not str or not r['stop_reason']):reject('MISSING_STOP_REASON')
    if status=='COMPLETED' and ('stop_reason' in r or any('error' in row for row in rows)):reject('FALSE_COMPLETION')
    if status=='RUNNING' and ('completed_at' in r or 'stop_reason' in r):reject('INVALID_RUNNING_RECORD')
    if rows and ('runtime' not in r or not exact_equal(r['runtime'],rows[0]['runtime'])):reject('RUNTIME_MISMATCH')
    trailing=r['resource_samples'][sample_index:]
    if status=='COMPLETED' and trailing:reject('UNEXPECTED_RESOURCE_EVIDENCE')
    if len(trailing)>2 or (trailing and rows and rows[-1]['status']!='MEASURED'):reject('UNEXPECTED_RESOURCE_EVIDENCE')
    # Extra samples may precede a stopped health/inference gate, never a later row.
    if len(trailing)==2:
        try:require_resources(trailing[0])
        except IntegrationError:reject('INVALID_RESOURCE_SEQUENCE')
    summary=summarize(rows,cases,repeats)
    if status!='RUNNING':
        if 'completed_at' not in r or not exact_equal(r.get('summary'),summary):reject('SUMMARY_MISMATCH')
    elif 'summary' in r:reject('INVALID_RUNNING_RECORD')
    # Snapshot completeness: never turn partial/corrupt evidence into a completed run.
    if len(r['resource_samples'])<2*len(rows):reject('MISSING_RESOURCE_EVIDENCE')
    return {'status':status,'execution_kind':r['execution_kind'],'summary':summary,'rows':rows,
            'planning_input':r['planning_input'],'planning_output':r['planning_output'],
            'measurement_eligible':r['execution_kind']=='LOCAL_RUNTIME' and summary['measured_count']>0,
            'complete_protocol':status=='COMPLETED' and repeats==3,
            'run_id':r['run_id'],'origin':'Execution origin is declared, not cryptographically authenticated.',
            'source_binding':{'commit':trust['source_commit'],'tree':trust['source_tree']}}
