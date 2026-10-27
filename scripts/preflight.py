"""Read-only native Windows preflight; never starts a server or inference."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fitlab_evaluation.lemonade import windows_memory,require_resources,IntegrationError,MODEL,MIN_AVAILABLE
root=Path(__file__).resolve().parents[1]
installed=Path.home()/'AppData/Local/lemonade_server/bin'
record={'timestamp':datetime.now(timezone.utc).isoformat(),'model':MODEL,'required_available_bytes':MIN_AVAILABLE,
        'inference_requests':0,'server_start_attempted':False,'model_load_attempted':False}
record['installed_version']=subprocess.run([str(installed/'lemonade.exe'),'--version'],capture_output=True,text=True,timeout=10).stdout.strip()
catalog_path=installed/'resources/server_models.json'
record['catalog_sha256']=hashlib.sha256(catalog_path.read_bytes()).hexdigest()
record['catalog_entry']=json.loads(catalog_path.read_text())[MODEL]
cache=Path.home()/'.cache/huggingface/hub/models--LiquidAI--LFM2.5-1.2B-Instruct-GGUF/snapshots'
record['cached_models']=[{'revision':p.parent.name,'file':p.name,'bytes':p.stat().st_size} for p in cache.glob('*/LFM2.5-1.2B-Instruct-Q4_K_M.gguf')]
record['memory']=windows_memory()
try:require_resources(record['memory']);record['resource_gate']='PASS'
except IntegrationError as exc:record['resource_gate']='FAIL';record['reason']=str(exc)
print(json.dumps(record,indent=2))
