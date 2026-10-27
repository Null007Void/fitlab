"""Capability Passport v2: deterministic projections from verified evidence only."""
import html
from .artifacts import ArtifactError,digest,stable_json,publish_bundle
from .evidence import validate_trust,verify_record,source_binding
from .grader import exact_equal
from fitlab_foundation.planner_cli import run_document
from fitlab_foundation.serialization import to_primitive


def build_report(trust,record=None,plan=None):
    pack=validate_trust(trust)
    verified=None if record is None else verify_record(record,trust)
    if record is not None and plan is not None:
        if any(s['model']['model_id']!=record['model'] for s in plan.get('scenarios',[])):raise ArtifactError('PLANNING_MODEL_MISMATCH')
        if record['planning_input'] is not None and not exact_equal(plan,record['planning_input']):raise ArtifactError('PLANNING_OVERRIDE_FORBIDDEN')
    planning_input=plan if plan is not None else (None if record is None else record['planning_input'])
    planning=None if plan is None else to_primitive(run_document(plan))
    if planning is None and verified is not None:planning=verified['planning_output']
    eligible=verified is not None and verified['measurement_eligible']
    summary=None if verified is None else verified['summary']
    state='NO_EVIDENCE' if verified is None else ('SYNTHETIC_ONLY' if verified['execution_kind']=='SYNTHETIC_TEST' else verified['status'])
    claims=[]
    def claim(identifier,label,kind,value,unit,basis,limitation):
        claims.append({'id':identifier,'label':label,'evidence_class':kind,'value':value,'unit':unit,'basis':basis,'limitation':limitation})
    claim('tasks','Task outcomes','MEASURED' if eligible else 'UNKNOWN',
          {'passed':summary['passed_count'],'planned':summary['planned_count'],'observed':summary['measured_count']} if eligible else None,
          'cases',['evaluation:rows'] if eligible else [],'Known toy tasks; no held-out general capability or reliability claim.')
    claim('latency','Client latency, median','MEASURED' if eligible else 'UNKNOWN',summary['median_client_latency_seconds'] if eligible else None,
          'seconds',['evaluation:rows.elapsed_seconds'] if eligible else [],'End-to-end nonstreaming latency, not decode throughput; cache state unknown.')
    for identifier,label,unit in [('peak_ram','Model peak RAM','bytes'),('ttft','Time to first token','seconds'),('decode','Decode throughput','tokens/s')]:
        claim(identifier,label,'UNKNOWN',None,unit,[],'Not collected by this protocol; null never means zero.')
    if planning is not None:
        models={s['scenario_id']:s['model']['model_id'] for s in planning_input['scenarios']}
        for row in planning['results']:
            workload=row.get('workload_plan',row)
            for key,result in sorted(workload['requirements'].items()):
                if type(result) is not dict or 'status' not in result:continue
                reasons=result.get('reasons',[])
                unsupported=any('UNSUPPORTED' in x['code'] for x in reasons)
                kind='UNSUPPORTED' if unsupported else (result['status'] if result['status'] in ('CALCULATED','ESTIMATED') else 'UNKNOWN')
                claim('plan:'+row['scenario_id']+':'+key,row['scenario_id']+' · '+models[row['scenario_id']]+' · '+key.replace('_',' ').capitalize(),kind,result['value'],result['unit'],
                      ['planning:'+row['scenario_id']+':'+key],'; '.join(result['limitations']+[r['detail'] for r in reasons]) or 'Derived from declared inputs, not a hardware measurement.')
    tasks=[]
    for case in pack['cases']:
        counts=summary['by_case'][case['id']] if eligible else None
        tasks.append({'id':case['id'],'category':case['category'],'observed':None if counts is None else counts['measured_count'],
                      'passed':None if counts is None else counts['passed_count'],'planned':None if summary is None else summary['by_case'][case['id']]['planned_count'],
                      'evidence_class':'MEASURED' if counts and counts['measured_count'] else 'UNKNOWN'})
    return {'schema_version':'fitlab-capability-passport-v2','title':'Lemonade FitLab',
            'source':{'binding':source_binding(),'commit':trust['source_commit'],'tree':trust['source_tree'],'trust_sha256':digest(stable_json(trust).encode()),
                      'task_pack_sha256':trust['task_pack_sha256'],'evaluation_sha256':None if record is None else digest(stable_json(record).encode()),
                      'planning_sha256':None if planning_input is None else digest(stable_json(planning_input).encode())},
            'evaluation_state':state,'capability_verdict':'OBSERVED_TOY_TASKS_ONLY' if eligible else 'NOT_EVALUATED',
            'complete_protocol':False if verified is None else verified['complete_protocol'] and eligible,
            'claims':claims,'tasks':tasks,'planning':planning,
            'provenance_limit':'Source/hash consistency and grades verified; execution origin is declared, not cryptographically authenticated.',
            'limitations':['Software tests and synthetic records never establish measured model capability.',
                          'A stopped or interrupted run retains its declared full denominator; unrun cases are not successes.',
                          'Calculated and estimated values use supplied planning assumptions and do not establish real hardware fit.',
                          'No TTFT, model peak RAM, cold-load performance or statistical reliability is measured.']}


def _escape(value):return html.escape(str(value),quote=True)


def render_report(report,trust,record=None,plan=None):
    # Export always rebuilds; a forged report dict cannot add observations.
    expected=build_report(trust,record,plan)
    from .grader import exact_equal
    if not exact_equal(report,expected):raise ArtifactError('REPORT_MISMATCH')
    esc=_escape
    def display(value):
        if value is None:return 'Unavailable'
        if type(value) is dict:return f"{value['passed']} / {value['planned']} planned · {value['observed']} observed"
        return str(value)
    cards=''.join('<article class="metric"><div class="kind '+esc(c['evidence_class'].lower())+'">'+esc(c['evidence_class'])+'</div><h3>'+esc(c['label'])+'</h3><strong>'+esc(display(c['value']))+'</strong><small>'+esc(c['unit'] or '')+'</small><p>'+esc(c['limitation'])+'</p></article>' for c in report['claims'][:5])
    rows=''.join('<tr><th>'+esc(t['id'])+'</th><td>'+esc(t['category'].replace('_',' '))+'</td><td>'+esc(t['evidence_class'])+'</td><td>'+('Unavailable' if t['observed'] is None else esc(str(t['passed'])+' / '+str(t['planned'])+' planned; '+str(t['observed'])+' observed'))+'</td></tr>' for t in report['tasks'])
    estimates=''.join('<tr><th>'+esc(c['label'])+'</th><td>'+esc(c['evidence_class'])+'</td><td>'+esc(display(c['value']))+' '+esc(c['unit'] or '')+'</td><td>'+esc(c['limitation'])+'</td></tr>' for c in report['claims'][5:])
    planning='<p>No planning metadata supplied. Hardware fit remains unknown.</p>' if not estimates else '<table><thead><tr><th>Requirement</th><th>Evidence</th><th>Value</th><th>Limits</th></tr></thead><tbody>'+estimates+'</tbody></table>'
    notice='No genuine model observations are available in this report.' if report['capability_verdict']=='NOT_EVALUATED' else 'Observed outcomes apply only to this fixed toy-task suite and declared runtime. They are not a general capability certification.'
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Lemonade FitLab | Capability Passport</title>
<style>
:root{font-family:system-ui,sans-serif;color:#173d32;background:#eff3e9;color-scheme:light}*{box-sizing:border-box}body{max-width:1180px;margin:auto;padding:40px 28px;line-height:1.5}header{display:flex;justify-content:space-between;gap:20px;align-items:center;border-bottom:2px solid #173d32;padding-bottom:30px}.eyebrow{letter-spacing:.15em;text-transform:uppercase;font-size:.75rem;font-weight:700}h1{font-size:clamp(2rem,5vw,4rem);line-height:1.05;margin:12px 0}.seal{border:2px solid #173d32;border-radius:50%;padding:26px;text-align:center;font-weight:700;background:#ddeb98;min-width:135px}h2{font-size:1.45rem;margin-bottom:8px}.notice{border-left:5px solid #be8521;background:#fff2cf;padding:20px 24px;margin:26px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px}.metric{background:#fff;border:1px solid #d9e2d0;border-radius:14px;padding:20px;min-width:0}.metric h3{font-size:.95rem}.metric strong{font-size:1.25rem;display:block;overflow-wrap:anywhere}.metric small{color:#58725d}.metric p{font-size:.8rem;color:#58725d}.kind{font-size:.65rem;letter-spacing:.09em;font-weight:800;padding:4px 8px;display:inline-block;border-radius:4px;background:#e9ece4}.measured{background:#d9edc6}.estimated,.calculated{background:#fff1c2}.unsupported{background:#f6d8cb}.unknown{background:#e9ece4}section{margin-top:30px;background:#fff;padding:24px;border:1px solid #d9e2d0;border-radius:14px}table{width:100%;border-collapse:collapse;font-size:.85rem}th,td{padding:12px 10px;border-bottom:1px solid #e3e9dd;text-align:left;vertical-align:top;overflow-wrap:anywhere}code{font-size:.75rem;overflow-wrap:anywhere}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:.8rem;margin:18px 0}.muted,footer{color:#58725d;font-size:.85rem}.tablewrap{overflow:auto}footer{margin-top:24px}@media(max-width:650px){body{padding:24px 14px}.seal{display:none}section{padding:16px}th,td{padding:8px 6px}}@media print{body{max-width:none;padding:0}.metric{break-inside:avoid}section{break-inside:avoid}.tablewrap{overflow:visible}}
</style></head><body><header><div><div class="eyebrow">Local AI · Evidence before claims</div><h1>Capability Passport</h1><p>Lemonade FitLab — what is known, what is estimated, and what remains unmeasured.</p></div><div class="seal">FITLAB<br><small>OFFLINE REPORT</small></div></header>
<div class="notice"><strong>'''+esc(report['evaluation_state'].replace('_',' '))+'''</strong><br>'''+esc(notice)+'''</div>
<div class="legend"><span class="kind measured">Measured</span><span class="kind estimated">Estimated / calculated</span><span class="kind unsupported">Unsupported</span><span class="kind unknown">Unknown</span></div><div class="grid">'''+cards+'''</div>
<section><h2>Task capability ledger</h2><p class="muted">Frozen eight-case suite. A missing result is unavailable, never zero latency or a passing result.</p><div class="tablewrap"><table><thead><tr><th>Task</th><th>Scope</th><th>Evidence</th><th>Outcome</th></tr></thead><tbody>'''+rows+'''</tbody></table></div></section>
<section><h2>Planning estimates</h2><p class="muted">Shared deterministic requirements engine; declared assumptions remain separate from measured behavior.</p><div class="tablewrap">'''+planning+'''</div></section>
<section><h2>Provenance and reproducibility</h2><p>Source binding: '''+esc(report['source']['binding'])+'''</p><p>Source: <code>'''+esc(report['source']['commit'])+'''</code></p><p>Task pack: <code>'''+esc(report['source']['task_pack_sha256'])+'''</code></p><p>Trust snapshot: <code>'''+esc(report['source']['trust_sha256'])+'''</code></p><p class="muted">'''+esc(report['provenance_limit'])+'''</p><ul>'''+''.join('<li>'+esc(x)+'</li>' for x in report['limitations'])+'''</ul></section><footer>Private engineering report · no scripts, remote assets, uploads, or external requests. JSON and manifest accompany this HTML. Publication and competition submission remain owner-controlled.</footer></body></html>
'''


def export_report(directory,trust,record=None,plan=None):
    report=build_report(trust,record,plan)
    rendered=render_report(report,trust,record,plan)
    files={'passport.json':stable_json(report),'passport.html':rendered,'trust.json':stable_json(trust)}
    if record is not None:files['evaluation.json']=stable_json(record)
    planning_input=plan if plan is not None else (None if record is None else record['planning_input'])
    if planning_input is not None:files['planning-input.json']=stable_json(planning_input)
    return publish_bundle(directory,files)
