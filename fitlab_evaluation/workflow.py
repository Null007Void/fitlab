"""One-command ready-only F5 run and deterministic Passport post-processing.

Never starts/stops a server, loads/unloads a model, changes config, or downloads.
A separately prepared, offline, already-loaded CPU runtime is required.
"""
import argparse
from .artifacts import BoundedParser
import http.client
import ipaddress
import json
import os
import socket
import sys
import threading
import time
from urllib.parse import urlsplit
from pathlib import Path
from .artifacts import ArtifactError,load_json,stable_json,publish_bundle
from .evidence import make_trust,validate_trust,verify_record
from .grader import strict_json,exact_equal
from .lemonade import LemonadeClient,MAX_BODY,validate_memory,require_resources,windows_memory,IntegrationError
from .run import evaluate,identity
from .report_v3 import export_report


def _is_local_reference(value):
    """True only for an explicit local path or loopback host."""
    if type(value) is not str or not value:
        return False
    lowered=value.lower()
    if lowered.startswith(('http://','https://','ws://','wss://')):
        try:host=urlsplit(lowered).hostname
        except ValueError:return False
    elif lowered.startswith(('/', '\\')) or (len(lowered)>=3 and lowered[1]==':' and lowered[2] in ('/','\\')):
        return True
    else:
        host=lowered.strip('[]')
    if host=='localhost' or host=='0.0.0.0':
        return True
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return False


def safe_runtime_config(port=13305,timeout=5):
    """Read only the locally documented config route. Persist only two safe flags."""
    started=time.monotonic()
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=timeout)
    timer=None
    try:
        connection.request('GET','/internal/config',headers={'Connection':'close'})
        sock=connection.sock
        def abort():
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                sock.close()
        timer=threading.Timer(max(.001,timeout-(time.monotonic()-started)),abort);timer.daemon=True;timer.start()
        response=connection.getresponse()
        if response.status!=200 or response.getheader('Content-Type','').split(';')[0].lower().strip()!='application/json':raise ArtifactError('RUNTIME_CONFIG_UNAVAILABLE')
        if response.getheader('Content-Encoding','identity')!='identity':raise ArtifactError('RUNTIME_CONFIG_UNAVAILABLE')
        data=response.read(MAX_BODY+1)
        if len(data)>MAX_BODY or time.monotonic()-started>timeout:raise ArtifactError('RUNTIME_CONFIG_UNAVAILABLE')
        config=strict_json(data.decode('utf-8'))
        if type(config) is not dict or config.get('offline') is not True or config.get('no_fetch_executables') is not True:
            raise ArtifactError('RUNTIME_NOT_PROVEN_OFFLINE')
        # A local-only measurement must not be routed to a cloud endpoint. The
        # check is allowlist-shaped: it refuses only when a routing field is
        # present and explicitly points somewhere other than local, so an
        # unfamiliar future configuration field cannot silently pass either.
        for field in ('host','endpoint','base_url','api_base','server_url','remote_url'):
            value=config.get(field)
            if type(value) is str and value and not _is_local_reference(value):
                raise ArtifactError('RUNTIME_REMOTE_ROUTING_REFUSED')
        for field in ('telemetry','analytics','cloud','use_cloud','cloud_routing'):
            value=config.get(field)
            if value is True:
                raise ArtifactError('RUNTIME_REMOTE_ROUTING_REFUSED')
        return {'offline':True,'no_fetch_executables':True}
    except ArtifactError:raise
    except (OSError,ValueError,RecursionError,http.client.HTTPException) as exc:raise ArtifactError('RUNTIME_CONFIG_UNAVAILABLE') from exc
    finally:
        if timer is not None:timer.cancel()
        connection.close()


def _checkpoint(path,record):
    import tempfile
    temporary=None
    try:
        # newline='' keeps stable_json's '\n' byte-exact on every platform:
        # sealed evidence is hashed byte-for-byte, so Windows text-mode
        # CRLF translation would make the digest checkout-dependent.
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='',dir=path.parent,prefix='.checkpoint-',delete=False) as handle:
            temporary=Path(handle.name);handle.write(stable_json(record));handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def _write_final_seal(directory, session):
    """Create and independently verify a bounded terminal evidence seal."""
    from .seal import inventory, verify_final_seal, require_finished_evidence

    if session.get('status') not in (
        'FINISHED', 'STOPPED', 'BLOCKED', 'INTERRUPTED'
    ):
        raise ArtifactError('INVALID_SEAL_STATUS')

    target = directory / 'final-seal.json'
    if os.path.lexists(target):
        raise ArtifactError('FINAL_SEAL_EXISTS')

    seal = {
        'schema_version': 'fitlab-final-seal-v1',
        'status': session['status'],
        'files': inventory(directory),
    }

    if session['status'] == 'FINISHED':
        require_finished_evidence(directory, seal['files'])

    data = stable_json(seal).encode('utf-8')
    with target.open('xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())

    if verify_final_seal(directory) != seal:
        raise ArtifactError('FINAL_SEAL_WRITE_MISMATCH')


def execute(directory,trust,*,memory=windows_memory,config=safe_runtime_config,client=None,repeats=3,plan=None):
    """Native path with injection seams only for explicit tests, never fake live labels."""
    validate_trust(trust)
    current={p.replace('\\','/'):h for p,h in identity().items()}
    if not exact_equal(current,trust['source_sha256']):raise ArtifactError('SOURCE_NOT_FROZEN')
    directory=Path(directory)
    publish_bundle(directory,{'trust.json':stable_json(trust),'bootstrap.json':stable_json({'schema_version':'fitlab-session-v1','status':'PREPARING','inference_requests':0})})
    session={'schema_version':'fitlab-session-v1','status':'PREPARING','inference_requests':0,
             'runtime_policy':'ready-only; no startup/load/download/configuration changes'}
    try:
        sample=validate_memory(memory());session['preflight']=sample;require_resources(sample)
        observed_config=config()
        # Validate before persistence; raw settings may contain secrets or bad values.
        if not exact_equal(observed_config,{'offline':True,'no_fetch_executables':True}):raise ArtifactError('RUNTIME_NOT_PROVEN_OFFLINE')
        session['runtime_config']={'offline':True,'no_fetch_executables':True}
        adapter=LemonadeClient() if client is None else client
        if type(adapter) is not LemonadeClient:raise ArtifactError('NATIVE_ADAPTER_REQUIRED')
        health=adapter.ready()
        if type(health.get('telemetry')) is not dict or health['telemetry'].get('enabled') is not False:
            raise ArtifactError('RUNTIME_TELEMETRY_NOT_DISABLED')
        compatibility=adapter.compatibility_snapshot()
        if compatibility.get('runtime_version') != health.get('version'):
            raise ArtifactError('RUNTIME_COMPATIBILITY_IDENTITY_MISMATCH')
        if compatibility.get('model_discovery',{}).get('status') != 'AVAILABLE_LISTED':
            raise ArtifactError('RUNTIME_MODEL_NOT_AVAILABLE')
        from .redact import redact_value
        # The compatibility snapshot embeds runtime launch/endpoint identity:
        # store the redacted copy (raw values already served validation).
        session['runtime_compatibility']=redact_value(compatibility)
        session['status']='EVALUATING';_checkpoint(directory/'session.json',session)
        # Recheck offline/no-fetch state before each health request through a guard.
        original_ready=adapter.ready
        def guarded_ready():
            if not exact_equal(config(),{'offline':True,'no_fetch_executables':True}):raise IntegrationError('runtime offline state changed')
            value=original_ready()
            if type(value.get('telemetry')) is not dict or value['telemetry'].get('enabled') is not False:raise IntegrationError('runtime telemetry state changed')
            return value
        adapter.ready=guarded_ready
        record=evaluate(plan,repeats,client=adapter,memory=memory,checkpoint=lambda r:_checkpoint(directory/'evaluation.json',r),execution_kind='LOCAL_RUNTIME')
        verified=verify_record(record,trust)
        export_report(directory/'passport',trust,record)
        session.update(status='FINISHED' if record['status']=='COMPLETED' else 'STOPPED',
                       measured_count=verified['summary']['measured_count'],evaluation_status=record['status'])
        # Row count includes attempted completions; STARTED may have been interrupted.
        session['inference_requests']=len(record['rows'])
    except KeyboardInterrupt:
        session['status']='INTERRUPTED'
    except Exception as exc:
        session['status']='BLOCKED';session['reason']=exc.code if isinstance(exc,ArtifactError) else 'RESOURCE_OR_RUNTIME_UNAVAILABLE'
    finally:
        # After a persistence error, count only durable attempts; unknown is not zero.
        if (directory/'evaluation.json').exists():
            try:
                previous,_=load_json(directory/'evaluation.json')
                session['inference_requests']=len(previous['rows'])
                session['request_count_basis']='durable attempted rows; an interrupted row may not have reached the server'
            except (ArtifactError,KeyError,TypeError):
                session['inference_requests']=None
                session['request_count_basis']='unavailable; evidence could not be reloaded'
        _checkpoint(directory/'session.json',session)
        _write_final_seal(directory,session)
    return session


def main(argv=None):
    parser=BoundedParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--output-dir',type=Path,required=True);run.add_argument('--trust',type=Path);run.add_argument('--repeats',type=int,choices=(1,2,3),default=3);run.add_argument('--plan',type=Path,help='Optional source-backed planning input; omit for a task-only run')
    resume=sub.add_parser('postprocess');resume.add_argument('--session-dir',type=Path,required=True);resume.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='postprocess':
            trust,_=load_json(args.session_dir/'trust.json');record,_=load_json(args.session_dir/'evaluation.json')
            export_report(args.output_dir,trust,record)
            result={'status':'WRITTEN','inference_requests':0}
        else:
            trust=make_trust() if args.trust is None else load_json(args.trust)[0]
            plan=None
            if args.plan is not None:
                # The planning input is validated through the strict F2
                # boundary before any runtime request, and it must name the
                # evaluated model.
                from fitlab_foundation.planner_cli import _read_bounded_document, run_document
                from fitlab_evaluation.lemonade import MODEL
                plan=_read_bounded_document(args.plan)
                run_document(plan)
                if any(s['model']['model_id']!=MODEL for s in plan['scenarios']):
                    raise ArtifactError('PLANNING_MODEL_MISMATCH')
            result=execute(args.output_dir,trust,repeats=args.repeats,plan=plan)
        print(stable_json(result),end='');return 0 if result['status'] in ('FINISHED','WRITTEN') else 2
    except ArtifactError as exc:code=exc.code
    except (OSError,ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):code='WORKFLOW_FAILED'
    print(stable_json({'status':'ERROR','code':code}),end='',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
