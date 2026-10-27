"""Independent, bounded verification of FitLab evidence."""
import hashlib
import re
from pathlib import Path
from .artifacts import ArtifactError, load_json, source_digest

REQUIRED = {"bootstrap.json", "trust.json", "manifest.json", "session.json"}
TERMINAL = {"FINISHED", "STOPPED", "BLOCKED", "INTERRUPTED"}
HASH = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")

def inventory(directory):
    root = Path(directory)
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ArtifactError("SEAL_UNSAFE_DIRECTORY")
    files = {}
    count = 0
    for p in root.rglob("*"):
        count += 1
        if count > 128:
            raise ArtifactError("SEAL_TOO_MANY_ENTRIES")
        if p.is_symlink() or p.is_junction():
            raise ArtifactError("SEAL_UNSAFE_PATH")
        if p.is_dir():
            continue
        if not p.is_file():
            raise ArtifactError("SEAL_UNSAFE_PATH")
        name = p.relative_to(root).as_posix()
        if name == "final-seal.json":
            continue
        if p.stat().st_size > 8 * 1024 * 1024:
            raise ArtifactError("SEAL_FILE_TOO_LARGE")
        h = hashlib.sha256()
        total = 0
        with p.open("rb") as stream:
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > 8 * 1024 * 1024:
                    raise ArtifactError("SEAL_FILE_TOO_LARGE")
                h.update(chunk)
        files[name] = h.hexdigest()
    if not REQUIRED.issubset(files):
        raise ArtifactError("SEAL_MISSING_REQUIRED_FILE")
    return files


def require_finished_evidence(directory, files):
    """Require complete, internally bound finished-campaign evidence."""
    root = Path(directory)

    if not {"evaluation.json", "passport/manifest.json"} <= files.keys():
        raise ArtifactError("SEAL_INCOMPLETE_FINISHED")

    session, _ = load_json(root / "session.json")
    evaluation, _ = load_json(root / "evaluation.json")
    passport, _ = load_json(root / "passport/manifest.json")

    if (type(session) is not dict or
        session.get("status") != "FINISHED" or
        session.get("evaluation_status") != "COMPLETED" or
        type(evaluation) is not dict or
        evaluation.get("status") != "COMPLETED"):
        raise ArtifactError("SEAL_FALSE_COMPLETION")

    if (type(passport) is not dict or
        passport.get("schema_version") != "fitlab-bundle-v1" or
        type(passport.get("files")) is not dict or
        not passport["files"]):
        raise ArtifactError("SEAL_INVALID_PASSPORT")

    components = passport["files"]
    expected = {"passport/manifest.json"}

    for name, sha in components.items():
        if (type(name) is not str or not name or
            Path(name).name != name or
            name == "manifest.json" or
            type(sha) is not str or HASH.fullmatch(sha) is None):
            raise ArtifactError("SEAL_INVALID_PASSPORT")

        full_name = "passport/" + name
        expected.add(full_name)
        if files.get(full_name) != sha:
            raise ArtifactError("SEAL_PASSPORT_HASH_MISMATCH")

    observed = {name for name in files if name.startswith("passport/")}
    if observed != expected:
        raise ArtifactError("SEAL_PASSPORT_COMPONENT_MISMATCH")


def verify_final_seal(directory):
    root = Path(directory)
    target = root / "final-seal.json"
    if target.is_symlink() or target.is_junction() or not target.is_file():
        raise ArtifactError("FINAL_SEAL_MISSING")
    seal, _ = load_json(target)
    if type(seal) is not dict or set(seal) != {"schema_version", "status", "files"}:
        raise ArtifactError("INVALID_FINAL_SEAL")
    if (type(seal["schema_version"]) is not str or seal["schema_version"] != "fitlab-final-seal-v1" or type(seal["status"]) is not str or seal["status"] not in TERMINAL):
        raise ArtifactError("INVALID_FINAL_SEAL")
    expected = seal["files"]
    if type(expected) is not dict or len(expected) > 128:
        raise ArtifactError("INVALID_FINAL_SEAL")
    for name, value in expected.items():
        if (type(name) is not str or not name or
            any(x in ("", ".", "..") for x in name.split("/")) or
            "\\" in name or type(value) is not str or
            HASH.fullmatch(value) is None):
            raise ArtifactError("INVALID_FINAL_SEAL")
    session, _ = load_json(root / "session.json")
    if session.get("status") != seal["status"]:
        raise ArtifactError("SEAL_STATUS_MISMATCH")
    if seal["status"] == "FINISHED":
        require_finished_evidence(root, expected)
    if inventory(root) != expected:
        raise ArtifactError("SEAL_HASH_MISMATCH")
    return seal


CAMPAIGN_SCHEMA = "fitlab-campaign-verification-v1"
EXECUTION_KINDS = {"LOCAL_RUNTIME", "SYNTHETIC_TEST"}


def _campaign_source(root):
    """Echo the source identity a sealed campaign declares for itself."""
    trust, _ = load_json(root / "trust.json")
    if type(trust) is not dict or trust.get("schema_version") != "fitlab-trust-v1":
        raise ArtifactError("CAMPAIGN_INVALID_TRUST")
    commit = trust.get("source_commit")
    tree = trust.get("source_tree")
    if (type(commit) is not str or COMMIT.fullmatch(commit) is None or
            type(tree) is not str or COMMIT.fullmatch(tree) is None):
        raise ArtifactError("CAMPAIGN_INVALID_TRUST")
    return trust, {"commit": commit, "tree": tree}


def verify_campaign(directory):
    """Compose the sealed checks into one verified finished-campaign view.

    Every sealed property is reused, not re-implemented: verify_final_seal()
    owns the tamper-evident inventory, the FINISHED preconditions and the
    passport component hash binding. This function adds only the campaign
    level composition, and each addition is a binding between two separately
    sealed facts:

    * the seal must be FINISHED, so a stopped or blocked directory never
      yields a campaign result;
    * evaluation.json must record a COMPLETED run of a known execution kind;
    * the passport's own copy of trust.json must hash to the bytes the seal
      covers, and its copy of evaluation.json must carry the same evaluation
      content (transport line endings ignored), so an echoed source identity or
      evaluation status is the sealed one rather than a file that happens to
      sit in the directory.

    Raises ArtifactError on every deviation; never upgrades a non-finished
    seal and never reports a synthetic record as a measurement.
    """
    root = Path(directory)
    seal = verify_final_seal(root)
    if seal["status"] != "FINISHED":
        raise ArtifactError("CAMPAIGN_NOT_FINISHED")

    evaluation, _ = load_json(root / "evaluation.json")
    passport, _ = load_json(root / "passport" / "manifest.json")
    _, source = _campaign_source(root)

    if type(evaluation) is not dict:
        raise ArtifactError("CAMPAIGN_INVALID_EVALUATION")
    status = evaluation.get("status")
    execution_kind = evaluation.get("execution_kind")
    if status != "COMPLETED":
        raise ArtifactError("CAMPAIGN_INVALID_EVALUATION")
    if type(execution_kind) is not str or execution_kind not in EXECUTION_KINDS:
        raise ArtifactError("CAMPAIGN_INVALID_EVALUATION")

    sealed = seal["files"]
    components = passport["files"]
    if components.get("trust.json") != sealed["trust.json"]:
        raise ArtifactError("CAMPAIGN_TRUST_BINDING_MISMATCH")

    # The campaign checkpoint writes evaluation.json in text mode while the
    # passport bundle is published in binary, so the two copies differ only by
    # transport line endings on Windows. Their sealed content hashes therefore
    # legitimately differ; compare the canonical form instead, so the same
    # evaluation must sit in both places or the passport was exported from a
    # different run than the one this directory sealed.
    if "evaluation.json" not in components:
        raise ArtifactError("CAMPAIGN_EVALUATION_BINDING_MISMATCH")
    try:
        passport_copy = (root / "passport" / "evaluation.json").read_bytes()
        campaign_copy = (root / "evaluation.json").read_bytes()
    except OSError as exc:
        raise ArtifactError("CAMPAIGN_EVALUATION_BINDING_MISMATCH") from exc
    if source_digest(passport_copy) != source_digest(campaign_copy):
        raise ArtifactError("CAMPAIGN_EVALUATION_BINDING_MISMATCH")

    return {
        "schema_version": CAMPAIGN_SCHEMA,
        "status": status,
        "execution_kind": execution_kind,
        "seal": seal,
        "passport": {
            "manifest_sha256": sealed["passport/manifest.json"],
            "components": {name: components[name] for name in sorted(components)},
        },
        "source": source,
    }