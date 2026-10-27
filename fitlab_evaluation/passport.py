"""Deterministic, offline F6 prototype. Measurement import is deliberately unavailable."""
import argparse
import html
import json
from pathlib import Path

STATUSES = {'ACCEPTED_BASELINE','REVIEW_PENDING','OFFLINE_REVIEW_PASS','CANDIDATE',
            'IMPLEMENTED','READY_NOT_RUN','NOT_STARTED'}


def build_passport(facts):
    if type(facts) is not dict or set(facts) != {'schema_version','project','source_commit','stages','evidence','limitations'}:
        raise ValueError('invalid passport facts')
    if facts['schema_version'] != 'fitlab-passport-facts-v1' or facts['project'] != 'Lemonade FitLab':
        raise ValueError('unsupported passport facts')
    commit=facts['source_commit']
    if type(commit) is not str or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('invalid source commit')
    if type(facts['stages']) is not list or len(facts['stages']) != 8:
        raise ValueError('expected F1 through F8')
    for i,stage in enumerate(facts['stages'],1):
        if (type(stage) is not dict or set(stage)!={'id','status','detail'} or stage['id']!=f'F{i}'
                or type(stage['status']) is not str or stage['status'] not in STATUSES):
            raise ValueError('invalid stage')
        _text(stage['detail'])
    for field in ('evidence','limitations'):
        if type(facts[field]) is not list or not 1<=len(facts[field])<=30:
            raise ValueError('invalid fact list')
        for value in facts[field]: _text(value)
    # Do not infer model capability, speed, fit, or reliability from engineering tests.
    return {'schema_version':'fitlab-passport-v1','facts':json.loads(json.dumps(facts)),
            'measurement_status':'UNAVAILABLE','observations':None,
            'capability_verdict':'NOT_EVALUATED',
            'measurement_placeholders':{
                'task_pass_rate':None,'client_latency_seconds':None,
                'decode_tokens_per_second':None,'time_to_first_token_seconds':None,
                'model_peak_ram_bytes':None,'reliability':None}}


def _text(value):
    if type(value) is not str or not value or len(value)>2000:
        raise ValueError('invalid display text')
    value.encode('utf-8',errors='strict')


def canonical(passport):
    if type(passport) is not dict or passport != build_passport(passport.get('facts')):
        raise ValueError('unverified passport content')
    return json.dumps(passport,sort_keys=True,ensure_ascii=True,indent=2,allow_nan=False)+'\n'


def render(passport):
    # Rebuild from strictly validated facts to reject forged measured fields.
    if type(passport) is not dict or passport != build_passport(passport.get('facts')):
        raise ValueError('unverified passport content')
    esc=lambda value:html.escape(value,quote=True)
    facts=passport['facts']
    stages=''.join('<tr><th>'+esc(s['id'])+'</th><td>'+esc(s['status'].replace('_',' '))+'</td><td>'+esc(s['detail'])+'</td></tr>' for s in facts['stages'])
    bullets=lambda values:''.join('<li>'+esc(value)+'</li>' for value in values)
    return '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Lemonade FitLab — Capability Passport</title>
<style>
:root{color-scheme:light;font-family:system-ui,sans-serif;color:#14342c;background:#f5f8f2}
body{max-width:980px;margin:40px auto;padding:0 24px;line-height:1.55}h1{font-size:2.5rem;line-height:1.12;margin:8px 0}
.tag{font-size:.8rem;letter-spacing:.12em;text-transform:uppercase;color:#45654a}.notice{background:#fff3c7;border-left:5px solid #b67c08;padding:18px 22px;margin:24px 0}
section{background:white;padding:20px 24px;margin:20px 0;border:1px solid #d5dfd0;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #e1e8dd;vertical-align:top}code{overflow-wrap:anywhere}.muted{color:#526258}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}.metric{background:#f4f7f1;padding:16px;border-radius:8px}.metric strong{display:block;font-size:1.2rem}footer{font-size:.8rem;color:#526258}@media print{body{margin:0}section{break-inside:avoid}}
</style>
<body><div class="tag">Local AI Capability Passport · offline prototype</div><h1>Lemonade FitLab</h1>
<p class="muted">Engineering readiness and measurement availability</p>
<div class="notice"><strong>Capability not yet evaluated.</strong> No new F5 model observations exist in this Passport. Passing software tests does not establish model quality, speed, hardware fit, or reliability.</div>
<section><h2>Measurements</h2><div class="metrics"><div class="metric">Task pass rate<strong>Unavailable</strong></div><div class="metric">Client latency<strong>Unavailable</strong></div><div class="metric">Model peak RAM<strong>Unavailable</strong></div><div class="metric">Time to first token<strong>Unavailable</strong></div></div><p>Null values mean unmeasured, never zero or a passing result.</p></section>
<section><h2>Engineering stages</h2><table><thead><tr><th>Stage</th><th>Status</th><th>Evidence boundary</th></tr></thead><tbody>'''+stages+'''</tbody></table></section>
<section><h2>Evidence</h2><ul>'''+bullets(facts['evidence'])+'''</ul><p>Source checkpoint: <code>'''+esc(facts['source_commit'])+'''</code></p></section>
<section><h2>Limits and next steps</h2><ul>'''+bullets(facts['limitations'])+'''</ul></section>
<footer>Private engineering artifact. No remote resources, scripts, or external requests. F6 prototype; independent end-to-end acceptance and publication remain outstanding.</footer></body></html>
'''


def main():
    # Legacy fact-only CLI is retained as a bounded migration error. It cannot
    # promote unauthenticated prose to a competition-facing evidence report.
    import sys
    print('{"code":"LEGACY_FACTS_DISABLED","status":"ERROR"}',file=sys.stderr)
    return 2

if __name__=='__main__':raise SystemExit(main())
