"""Read-only tracked-file classification; emits private audit JSON, never exports."""
import hashlib
import json
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
# The proposed public package scope. Review this list before every export.
selected={
    'README.md',
    'docs/ARCHITECTURE.md',
    'docs/FORMULAS_AND_LIMITATIONS.md',
    'docs/QUICKSTART.md',
    'docs/INSTALL_AND_REPRODUCE.md',
    'docs/PRIVACY.md',
    'docs/TROUBLESHOOTING.md',
    'docs/EVIDENCE_VERIFICATION.md',
    'docs/F5_TURNKEY.md',
    'docs/F5_MEASUREMENT_PROTOCOL.md',
    'docs/capability-passport-v3.schema.json',
    'docs/evaluation-result-v2.schema.json',
}
# Internal status and planning documents that are private by default.
internal={
    'SPRINT_STATUS.md',
    'docs/SPRINT_RESUME.md',
    'docs/PRODUCT_GUIDE.md',
    'docs/RELEASE_READINESS.md',
    'docs/RISK_REGISTER.md',
    'docs/SUBMISSION_DRAFT.md',
    'docs/DEMO_STORYBOARD.md',
    'docs/F8_OFFLINE_READINESS.md',
    'docs/capability-passport-v2.schema.json',
    'scripts/release_inventory.py',
}
paths=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
files=[]
for name in sorted(filter(None,paths)):
    data=(root/name).read_bytes()
    if name in selected:
        category='SOURCE_CANDIDATE_REQUIRES_OWNER_REVIEW'
    elif name in internal:
        category='INTERNAL_PRIVATE_BY_DEFAULT'
    elif name.startswith(('fitlab_foundation/','fitlab_evaluation/','fixtures/','examples/','tests/')):
        category='SOURCE_CANDIDATE_REQUIRES_OWNER_REVIEW'
    else:
        category='PRIVATE_DEFAULT'
    files.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'category':category})
counts={}
for entry in files:
    counts[entry['category']]=counts.get(entry['category'],0)+1
print(json.dumps({
    'schema_version':'fitlab-release-inventory-v2',
    'export_created':False,
    'publication_authorized':False,
    'license_grant_present':False,
    'scope':'Tracked files at invocation; this inventory is excluded from itself to avoid recursive hashes. No classification grants release permission.',
    'note':'SOURCE_CANDIDATE means proposed for the public package and still requires owner review. It is not release clearance.',
    'category_counts':counts,
    'files':[f for f in files if f['path']!='evidence/review3/release-inventory.json'],
},sort_keys=True,indent=2))
