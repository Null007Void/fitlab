"""One-shot LIVE-002 public-export sanitizer (deterministic, auditable).

Pipeline per file (evaluation.json, session.json):
  1. parse the sealed bytes as JSON
  2. redact ONLY the runtime launch/path strings via the product's own
     redact.redact_value (same engine the product uses for shareable reports)
  3. re-serialize with the product's stable_json (sorted keys, ensure_ascii,
     trailing newline) and LF endings
  4. write bytes
Then: rebuild final-seal.json via the product's _write_final_seal-equivalent
(inventory + FINISHED gates) and verify with verify_campaign().

 passport/* bundle files are byte-UNTOUCHED (their bundle hashes are inside
 manifest/final-seal and the passport already redacts shared prose).
"""
import hashlib
import json
import sys
from pathlib import Path

EXPORT = Path(__file__).resolve().parents[1]  # repository root
CAMP = EXPORT / "evidence/phase-a/live-validation-001"
sys.path.insert(0, str(EXPORT))

from fitlab_evaluation.redact import redact_value, contains_private_detail  # noqa: E402
from fitlab_evaluation.artifacts import stable_json  # noqa: E402
from fitlab_evaluation.seal import inventory, verify_campaign  # noqa: E402

TARGET_KEYS = {"launch_command", "backend_url", "model_path"}
FILES = ("evaluation.json", "session.json")


def scrub(value):
    """Redact private detail inside ONLY the runtime-identity keys."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in TARGET_KEYS:
                out[key] = redact_value(item)
            elif key == "all_models_loaded":
                out[key] = [scrub(x) if isinstance(x, dict) else x for x in item]
            else:
                out[key] = scrub(item)
        return out
    if isinstance(value, list):
        return [scrub(x) for x in value]
    return value


def main():
    for name in FILES:
        raw = (CAMP / name).read_bytes()
        data = json.loads(raw.decode("utf-8"))
        redacted = scrub(data)
        text = stable_json(redacted)
        assert "\r" not in text
        assert not contains_private_detail(text), name
        (CAMP / name).write_bytes(text.encode("utf-8"))
        print(f"{name}: rewritten, LF, {len(raw)} -> {len(text.encode())} bytes")

    # The passport bundle echoes evaluation.json; its copy must carry the
    # SAME sanitized content (verify_campaign binds the two by digest), and
    # the bundle manifest must hash the current components.
    campaign_eval = (CAMP / "evaluation.json").read_bytes()
    (CAMP / "passport" / "evaluation.json").write_bytes(campaign_eval)
    from fitlab_evaluation.artifacts import digest
    components = {}
    for component in sorted((CAMP / "passport").iterdir()):
        if component.is_file() and component.name != "manifest.json":
            components[component.name] = digest(component.read_bytes())
    passport_manifest = {"schema_version": "fitlab-bundle-v1",
                         "files": components}
    (CAMP / "passport" / "manifest.json").write_bytes(
        stable_json(passport_manifest).encode("utf-8"))

    # Rebuild the seal from the current tree with the ORIGINAL status
    # (session.json still says FINISHED/COMPLETED — scrubbing touched only
    # runtime-identity keys).
    session = json.loads((CAMP / "session.json").read_text("utf-8"))
    assert session["status"] == "FINISHED", session["status"]
    seal = {
        "schema_version": "fitlab-final-seal-v1",
        "status": session["status"],
        "files": inventory(CAMP),
    }
    (CAMP / "final-seal.json").write_bytes(
        stable_json(seal).encode("utf-8"))

    result = verify_campaign(CAMP)
    print("verify_campaign:", result["status"], result["execution_kind"])
    assert result["status"] == "COMPLETED"
    assert result["execution_kind"] == "LOCAL_RUNTIME"
    print("SOURCE (historical record, unchanged):", result["source"])
    print("SEAL-REBUILD-OK")


if __name__ == "__main__":
    main()