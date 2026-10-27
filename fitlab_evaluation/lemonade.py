"""Fixed loopback transport for an already-loaded, verified CPU model.

No server startup, model load/download, proxy, redirect, retry, or tool execution.
"""
import ctypes
import http.client
import json
import math
import os
import socket
import time
from .grader import strict_json, optional_fields_error

MODEL = 'LFM2.5-1.2B-Instruct-GGUF'
VERSION = '2026.42.1'
TARGET_VERSION = '2026.43.3'
SUPPORTED_VERSIONS = frozenset((VERSION, TARGET_VERSION))
CHECKPOINT = 'LiquidAI/LFM2.5-1.2B-Instruct-GGUF:LFM2.5-1.2B-Instruct-Q4_K_M.gguf'
MIN_AVAILABLE = math.ceil(4.481 * 2**30)
MAX_BODY = 256 * 1024


class IntegrationError(ValueError):
    pass


def windows_memory():
    """Read native memory counters without dependencies or subprocesses."""
    if os.name != 'nt':
        raise IntegrationError('Windows-native memory measurement required')
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in
            ('total_physical','available_physical','total_pagefile','available_pagefile',
             'total_virtual','available_virtual','available_extended_virtual')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise IntegrationError('memory counters unavailable')
    return {'total_physical_bytes':status.total_physical,
            'available_physical_bytes':status.available_physical,
            'memory_load_percent':status.load,
            'available_commit_bytes':status.available_pagefile}


def validate_memory(snapshot):
    fields={'total_physical_bytes','available_physical_bytes','memory_load_percent','available_commit_bytes'}
    if type(snapshot) is not dict or set(snapshot) != fields:
        raise IntegrationError('invalid memory snapshot fields')
    if any(type(snapshot[field]) is not int or not 0 <= snapshot[field] <= 2**64-1 for field in fields):
        raise IntegrationError('invalid memory counter')
    if (snapshot['total_physical_bytes'] <= 0 or snapshot['available_physical_bytes'] > snapshot['total_physical_bytes']
            or snapshot['memory_load_percent'] > 100):
        raise IntegrationError('inconsistent memory counters')
    return dict(snapshot)


def require_resources(snapshot):
    snapshot=validate_memory(snapshot)
    if (10 * snapshot['available_physical_bytes'] <= snapshot['total_physical_bytes']
            or snapshot['available_physical_bytes'] < MIN_AVAILABLE or snapshot['memory_load_percent'] >= 90
            or snapshot['available_commit_bytes'] < MIN_AVAILABLE):
        raise IntegrationError('resource gate failed: requires 4.481 GiB available physical and commit, load below 90%')


def bounded_json(value, label):
    try:
        encoded=json.dumps(value,allow_nan=False,ensure_ascii=True)
        if len(encoded)>MAX_BODY*2:
            raise IntegrationError(label+' too large')
        return strict_json(encoded)
    except (TypeError,ValueError,RecursionError) as exc:
        if isinstance(exc,IntegrationError): raise
        raise IntegrationError(label+' is not bounded JSON') from exc


def _optional_nonnegative_number(value, label):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise IntegrationError('invalid '+label)
    return value


def validate_runtime_stats(stats):
    """Normalize optional 42.1/43.3 telemetry without inventing measurements."""
    stats=bounded_json(stats,'runtime stats')
    if type(stats) is not dict:
        raise IntegrationError('invalid runtime stats type')
    live=stats.get('live')
    if live is None:
        active=estimated=None
    else:
        if type(live) is not dict:
            raise IntegrationError('invalid live telemetry')
        active=live.get('active_requests')
        if type(active) is not int or active < 0:
            raise IntegrationError('invalid active requests')
        estimated=_optional_nonnegative_number(live.get('estimated_tokens_per_second'),
                                               'estimated live throughput')
    decode=_optional_nonnegative_number(stats.get('tokens_per_second'),
                                        'completed decode throughput')
    prefill_value=stats.get('prefill_tokens_per_second',stats.get('pp_tps'))
    prefill=_optional_nonnegative_number(prefill_value,'completed prefill throughput')
    ttft=_optional_nonnegative_number(stats.get('time_to_first_token'),
                                      'time to first token')
    return {'live':{'active_requests':active,
                    'estimated_tokens_per_second':estimated,
                    'measurement_kind':'best_effort_stream_estimate'},
            'completed':{'decode_tokens_per_second':decode,
                         'prefill_tokens_per_second':prefill,
                         'time_to_first_token_seconds':ttft,
                         'decode_measurement_kind':'completed_request_stat',
                         'prefill_measurement_kind':('reported_completed_prefill_stat'
                                                     if prefill is not None else 'unavailable')}}


def _optional_percent(value, label):
    value=_optional_nonnegative_number(value,label)
    if value is not None and value > 100:
        raise IntegrationError('invalid '+label)
    return value


def validate_system_stats(stats):
    """Validate host telemetry while keeping inference-device attribution unknown."""
    stats=bounded_json(stats,'system stats')
    if type(stats) is not dict:
        raise IntegrationError('invalid system stats type')
    memory=_optional_nonnegative_number(stats.get('memory_gb'),'system memory usage')
    if memory is None:
        raise IntegrationError('missing system memory usage')
    cpu=_optional_percent(stats.get('cpu_percent'),'CPU utilization')
    gpu_percent=_optional_percent(stats.get('gpu_percent'),'GPU utilization')
    vram=_optional_nonnegative_number(stats.get('vram_gb'),'GPU memory usage')
    npu=_optional_percent(stats.get('npu_percent'),'NPU utilization')
    raw_gpus=stats.get('gpus',[])
    if type(raw_gpus) is not list:
        raise IntegrationError('invalid GPU inventory')
    gpus=[]; ids=set()
    for raw in raw_gpus:
        required={'id','vendor','name','memory_type','gpu_percent','memory_total_gb','memory_used_gb'}
        if type(raw) is not dict or not required<=raw.keys():
            raise IntegrationError('invalid GPU telemetry entry')
        if (type(raw['id']) is not str or not raw['id'] or raw['id'] in ids
                or type(raw['vendor']) is not str or not raw['vendor']
                or type(raw['name']) is not str or not raw['name']
                or raw['memory_type'] not in ('shared','dedicated','unknown')):
            raise IntegrationError('invalid GPU identity')
        ids.add(raw['id'])
        total=_optional_nonnegative_number(raw['memory_total_gb'],'GPU total memory')
        used=_optional_nonnegative_number(raw['memory_used_gb'],'GPU used memory')
        if total is not None and used is not None and used > total+1e-6:
            raise IntegrationError('GPU used memory exceeds total')
        gpus.append({'id':raw['id'],'vendor':raw['vendor'],'name':raw['name'],
                     'memory_type':raw['memory_type'],
                     'gpu_percent':_optional_percent(raw['gpu_percent'],'GPU utilization'),
                     'memory_total_gb':total,'memory_used_gb':used})
    primary_id=stats.get('primary_gpu_id')
    if primary_id is not None and (type(primary_id) is not str or primary_id not in ids):
        raise IntegrationError('invalid primary GPU identity')
    if gpus and primary_id is None:
        raise IntegrationError('missing primary GPU identity')
    primary=next((item for item in gpus if item['id']==primary_id),None)
    return {'cpu_percent':cpu,'memory_gb':memory,'gpu_percent':gpu_percent,
            'vram_gb':vram,'npu_percent':npu,'primary_gpu_id':primary_id,
            'primary_gpu':primary,'gpus':gpus,
            'device_attribution':('host_primary_display_device' if primary else 'unverified'),
            'inference_device_verified':False}


def classify_model_discovery(catalog, target=MODEL, error=None):
    """Classify discovery without pulling a model or installing a backend."""
    if type(target) is not str or not target:
        raise IntegrationError('invalid target model')
    catalog=bounded_json(catalog,'model catalog')
    if type(catalog) is not dict or type(catalog.get('data')) is not list:
        raise IntegrationError('invalid model catalog')
    ids=[]
    for item in catalog['data']:
        if type(item) is not dict or type(item.get('id')) is not str or not item['id']:
            raise IntegrationError('invalid model catalog entry')
        ids.append(item['id'])
    if len(ids)!=len(set(ids)):
        raise IntegrationError('duplicate model catalog identity')
    status='AVAILABLE_LISTED' if target in ids else 'NOT_LISTED'
    reason=('target present in model catalog' if status=='AVAILABLE_LISTED'
            else 'absence may mean hidden guest-backend model; no install or pull attempted')
    if error is not None:
        error=bounded_json(error,'model discovery error')
        detail=error.get('error') if type(error) is dict else None
        if type(detail) is not dict:
            raise IntegrationError('invalid model discovery error')
        if detail.get('code')=='model_not_supported' or detail.get('type')=='model_not_supported':
            requested=detail.get('requested_model',target)
            if requested!=target:
                raise IntegrationError('model discovery error identity mismatch')
            status='UNSUPPORTED';reason='runtime returned model_not_supported'
        else:
            status='API_ERROR';reason='runtime returned a non-support-classified error'
    return {'model':target,'status':status,'reason':reason,
            'install_attempted':False,'pull_attempted':False}


class LemonadeClient:
    def __init__(self, port=13305, timeout=30):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('invalid loopback port')
        if type(timeout) not in (int,float) or not 0 < timeout <= 60 or not math.isfinite(timeout):
            raise ValueError('timeout must be finite, positive, at most 60 seconds')
        self.port, self.timeout = port, timeout

    def request(self, method, path, payload=None):
        allowed={('GET','/api/v1/health'),('GET','/api/v1/stats'),
                 ('GET','/api/v1/system-stats'),('GET','/api/v1/models?show_all=true'),
                 ('POST','/v1/chat/completions')}
        if (method,path) not in allowed:
            raise IntegrationError('endpoint not allowed')
        body = None if payload is None else json.dumps(payload,allow_nan=False).encode('utf-8')
        if body is not None and len(body) > 16384:
            raise IntegrationError('request too large')
        started = time.monotonic()
        connection = http.client.HTTPConnection('127.0.0.1',self.port,timeout=self.timeout)
        try:
            connection.request(method,path,body=body,headers={'Content-Type':'application/json','Connection':'close'})
            # Socket timeout bounds individual operations; timer bounds aggregate headers/body.
            import threading
            sock = connection.sock
            def abort():
                if sock is not None:
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    sock.close()
            timer = threading.Timer(max(0.001,self.timeout-(time.monotonic()-started)),abort)
            timer.daemon=True
            timer.start()
            try:
                response = connection.getresponse()
                if response.status != 200:
                    raise IntegrationError('HTTP status ' + str(response.status))
                if response.getheader('Content-Encoding','identity') != 'identity':
                    raise IntegrationError('encoded body unsupported')
                if response.getheader('Content-Type','').split(';')[0].strip().lower() != 'application/json':
                    raise IntegrationError('response is not JSON')
                raw = response.read(MAX_BODY+1)
                if len(raw) > MAX_BODY:
                    raise IntegrationError('response too large')
                if time.monotonic()-started > self.timeout:
                    raise IntegrationError('request deadline exceeded')
                parsed = strict_json(raw.decode('utf-8'))
                if type(parsed) is not dict:
                    raise IntegrationError('response must be object')
                return parsed
            finally:
                timer.cancel()
        except IntegrationError:
            raise
        except (OSError, http.client.HTTPException, ValueError, RecursionError) as exc:
            raise IntegrationError('transport or JSON failure: '+type(exc).__name__) from exc
        finally:
            connection.close()

    def ready(self):
        return validate_health(self.request('GET','/api/v1/health'))

    def compatibility_snapshot(self):
        health=self.ready()
        stats=validate_runtime_stats(self.request('GET','/api/v1/stats'))
        system=validate_system_stats(self.request('GET','/api/v1/system-stats'))
        discovery=classify_model_discovery(
            self.request('GET','/api/v1/models?show_all=true'))
        return {'runtime_version':health['version'],'runtime_health':health,
                'runtime_stats':stats,'system_stats':system,
                'model_discovery':discovery,
                'scope':'read-only loopback compatibility inspection; no pull or install'}

    def complete(self, prompt):
        payload = build_request(prompt)
        start = time.perf_counter()
        response = self.request('POST','/v1/chat/completions',payload)
        elapsed = time.perf_counter()-start
        validate_response(response)
        return {'request':payload,'response':response,'elapsed_seconds':elapsed,
                'timing_kind':'client end-to-end nonstreaming; NOT decode throughput or TTFT'}

def validate_health(health):
    health=bounded_json(health,'health response')
    if type(health) is not dict:
        raise IntegrationError('invalid health response type')
    if health.get('status') != 'ok' or health.get('version') not in SUPPORTED_VERSIONS:
        raise IntegrationError('runtime health/version mismatch')
    models = health.get('all_models_loaded')
    if type(models) is not list or len(models) != 1 or type(models[0]) is not dict:
        raise IntegrationError('requires exactly one loaded model')
    model = models[0]
    options = model.get('recipe_options')
    if type(options) is not dict:
        raise IntegrationError('missing runtime configuration')
    if (model.get('model_name') != MODEL or model.get('checkpoint') != CHECKPOINT
        or model.get('device') != 'cpu' or model.get('recipe') != 'llamacpp'
        or model.get('loaded') is not True or model.get('backend_alive') is not True
        or model.get('backend_health') != 'ready' or model.get('is_busy') is not False
        or model.get('is_streaming') is not False or options.get('llamacpp_backend') != 'cpu'
        or type(options.get('ctx_size')) is not int or options['ctx_size'] != 2048):
        raise IntegrationError('model identity, CPU configuration or readiness mismatch')
    # Require a modest, explicit thread budget; no default all-core inference.
    import shlex
    raw_args = options.get('llamacpp_args')
    if type(raw_args) is not str or len(raw_args)>256:
        raise IntegrationError('invalid CPU tuning arguments')
    try:
        args = shlex.split(raw_args)
    except ValueError as exc:
        raise IntegrationError('invalid CPU tuning arguments') from exc
    if args != ['--parallel','1','--threads','2','--threads-batch','2']:
        raise IntegrationError('requires --parallel 1 --threads 2 --threads-batch 2')
    return health



def build_request(prompt):
    if type(prompt) is not str or not prompt:
        raise IntegrationError('invalid prompt')
    try:
        if len(prompt.encode('utf-8')) > 8192:
            raise IntegrationError('invalid prompt')
    except UnicodeError as exc:
        raise IntegrationError('invalid prompt unicode') from exc
    return {'model':MODEL,'messages':[{'role':'user','content':prompt}],
            'temperature':0.1,'max_tokens':128,'stream':False,
            'chat_template_kwargs':{'enable_thinking':False}}


def validate_response(response):
    if type(response) is not dict or response.get('model') != MODEL:
        raise IntegrationError('response model or type mismatch')
    choices = response.get('choices')
    if type(choices) is not list or len(choices)!=1 or type(choices[0]) is not dict:
        raise IntegrationError('expected one completion')
    choice=choices[0]
    message=choice.get('message')
    if (type(message) is not dict or message.get('role') != 'assistant'
            or type(message.get('content')) is not str):
        raise IntegrationError('invalid completion message')
    if type(choice.get('finish_reason')) is not str:
        raise IntegrationError('missing or malformed finish reason')
    problem=optional_fields_error(message.get('tool_calls'),message.get('function_call'),message.get('refusal'))
    if problem:
        raise IntegrationError(problem)
    try:
        message['content'].encode('utf-8')
    except UnicodeError as exc:
        raise IntegrationError('invalid completion unicode') from exc
    return response


def validate_result(result, prompt):
    if type(result) is not dict:
        raise IntegrationError('invalid adapter result type')
    required={'request','response','elapsed_seconds'}
    if not required <= result.keys() or result.keys()-required-{'timing_kind'}:
        raise IntegrationError('invalid adapter result fields')
    elapsed=result['elapsed_seconds']
    if type(elapsed) not in (int,float) or not 0 <= elapsed <= 60 or not math.isfinite(elapsed):
        raise IntegrationError('invalid adapter elapsed time')
    # Exact JSON types matter: true must not equal 1 in request settings.
    from .grader import exact_equal
    if not exact_equal(result['request'], build_request(prompt)):
        raise IntegrationError('adapter request type mismatch')
    validate_response(result['response'])
    if 'timing_kind' in result and type(result['timing_kind']) is not str:
        raise IntegrationError('invalid timing metadata')
    return bounded_json(result,'adapter result')
