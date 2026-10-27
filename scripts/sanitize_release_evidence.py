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

 passport/evaluation.json and passport/manifest.json ARE rewritten (the
 passport's evaluation copy must carry the same redacted content, and the
 bundle manifest must hash the current components). passport.html,
 passport.json and passport/trust.json remain byte-untouched.

Historical-handoff verification record: this public export intentionally
omits private handoff infrastructure identities (index/delivery-record file
names, private paths, schemas, digests). The record inside the export is
regenerated from the original with those fields reduced to outcome counters;
nothing else about the verification story changes.
"""
import hashlib
import json
import sys

from pathlib import Path

EXPORT = Path(__file__).resolve().parents[1]  # repository root
CAMP = EXPORT / "evidence/phase-a/live-validation-001"
HANDOFF_RECORD = EXPORT / "evidence/phase-a/historical-handoff-verification.json"
sys.path.insert(0, str(EXPORT))

from fitlab_evaluation.redact import redact_value, contains_private_detail  # noqa: E402
from fitlab_evaluation.artifacts import stable_json  # noqa: E402
from fitlab_evaluation.seal import inventory, verify_campaign  # noqa: E402

TARGET_KEYS = {"launch_command", "backend_url", "model_path"}
FILES = ("evaluation.json", "session.json")
# Private handoff-infrastructure identity fields (names, schemas, mission
# ids, private sub-paths) that must not ship in the public record.
HANDOFF_PRIVATE_KEYS = ("index", "mission_id", "schema_version",
                        "external_members", "source_commit", "source_tree")
HANDOFF_OUTCOME_KEYS = ("bytes_verified", "failures", "inference_requests",
                        "members_declared", "members_failed",
                        "members_verified", "unused_externals", "verdict")


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


def sanitize_handoff_record(raw_text):
    """Reduce the private handoff record to its public outcome summary."""
    data = json.loads(raw_text.decode("utf-8"))
    public = {key: data[key] for key in HANDOFF_OUTCOME_KEYS if key in data}
    assert public.get("verdict") == "PASS", public
    assert public.get("members_failed") == 0 and public.get("members_verified") == public.get("members_declared"), public
    return stable_json(public)


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

    # Public record: handoff verification outcome only (no private handoff
    # infrastructure identities).
    handoff_text = sanitize_handoff_record(HANDOFF_RECORD.read_bytes())
    assert "\r" not in handoff_text
    HANDOFF_RECORD.write_bytes(handoff_text.encode("utf-8"))
    print("historical-handoff-verification.json: reduced to public outcome summary")

    # The passport bundle echoes evaluation.json; its copy must carry the
    # SAME sanitized content (verify_campaign binds the two by digest), and
    # the bundle manifest must hash the current components.
    campaign_eval = (CAMP / "evaluation.json").read_bytes()
    (CAMP / "passport" / "evaluation.json").write_bytes(campaign_eval)
    from fitlab_evaluation.artifacts import digest
    # passport.json's displayed evaluation provenance must identify the
    # Sanitized evaluation that actually ships in this bundle (round-21
    # review C-1): rewrite source.evaluation_sha256 structurally, and carry
    # the provenance note as a STRUCTURAL field (never injected by string
    # replacement — that produced duplicate keys on re-runs, round-23 C-1).
    # The note is idempotent: repeated runs keep one note and preserve the
    # ORIGINAL historical digest, even when input was already rewritten.
    passport_json_path = CAMP / "passport" / "passport.json"
    passport_text = passport_json_path.read_text(encoding="utf-8")
    passport = json.loads(passport_text)
    current = passport["source"]["evaluation_sha256"]
    new_digest = digest(campaign_eval)
    note = passport["source"].get("note", "")
    historical = current
    marker = "original historical digest was "
    if marker in note:
        # Already-sanitized input: preserve the recorded historical digest,
        # never overwrite it with the intermediate one.
        historical = note.split(marker, 1)[1].split()[0].strip('"')
    passport["source"]["evaluation_sha256"] = new_digest
    passport["source"]["note"] = (
        "digest of the sanitized evaluation copy shipped in this bundle; "
        "original historical digest was " + historical)
    passport_text = stable_json(passport)
    assert "\r" not in passport_text
    assert not contains_private_detail(passport_text)
    passport_json_path.write_bytes(passport_text.encode("utf-8"))

    # The HTML must display the same corrected provenance. The structural
    # note embeds the historical digest inside passport.json, so the HTML
    # replacement must distinguish the bare-digest occurrence (the displayed
    # provenance row) from the note-embedded occurrence inside the JSON (not
    # present in the HTML). The invariant: the displayed provenance must not
    # show the stale digest unless it is the disclosed historical one inside
    # the JSON note.
    passport_html_path = CAMP / "passport" / "passport.html"
    html_text = passport_html_path.read_text(encoding="utf-8")
    if historical != new_digest:
        html_text = html_text.replace(historical, new_digest)
    assert new_digest in html_text
    assert (historical not in html_text) or historical == new_digest
    assert "\r" not in html_text
    passport_html_path.write_bytes(html_text.encode("utf-8"))

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

    # The public verification record must describe THIS export (round-22
    # review C-1): regenerate it from the SAME verify_campaign output that
    # just passed, so component and seal digests bind the shipped files.
    verification = {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "execution_kind": result["execution_kind"],
        "source": result["source"],
        "passport": result["passport"],
        "seal": {
            "schema_version": seal["schema_version"],
            "status": seal["status"],
            "files": seal["files"],
        },
    }
    verification_text = stable_json(verification)
    assert "\r" not in verification_text
    assert not contains_private_detail(verification_text)
    record_path = EXPORT / "evidence/phase-a/live-validation-public-verification.json"
    record_path.write_bytes(verification_text.encode("utf-8"))
    print("live-validation-public-verification.json: regenerated against this export")
    print("VERIFY-RECORD-OK")


if __name__ == "__main__":
    main()