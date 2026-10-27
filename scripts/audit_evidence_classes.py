"""Audit the evidence class of every judge-facing passport field.

Read-only over an existing passport.json: the stored machine class is reported
as found, next to the owner-vocabulary label the current presentation layer
would render for it. Nothing is regenerated and no value is rewritten.

Usage:
    python scripts/audit_evidence_classes.py <passport.json> [<passport.json> ...]

Emits one JSON document per artifact on stdout.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fitlab_evaluation.report_v3 import OWNER_EVIDENCE_CLASSES, evidence_label


def audit(path):
    payload = json.loads(Path(path).read_text("utf-8"))
    rows = []
    for group in ("claims", "tasks"):
        for item in payload.get(group) or []:
            kind = item.get("evidence_class")
            rows.append(
                {
                    "group": group,
                    "id": item.get("id"),
                    "machine_class": kind,
                    "owner_label": None if kind is None else evidence_label(kind),
                    "value_present": (
                        item.get("value") is not None
                        if group == "claims"
                        else item.get("observed") is not None
                    ),
                }
            )
    counts = {}
    for row in rows:
        counts[row["owner_label"]] = counts.get(row["owner_label"], 0) + 1
    return {
        "artifact": Path(path).name,
        "schema_version": payload.get("schema_version"),
        "evaluation_state": payload.get("evaluation_state"),
        "capability_verdict": payload.get("capability_verdict"),
        "stored_report_evidence_class": payload.get("evidence_class"),
        "stored_historical_campaign": payload.get("historical_campaign"),
        "stored_label_field_present": any("evidence_label" in row for row in
                                          (payload.get("claims") or [])),
        "fields": rows,
        "owner_label_counts": dict(sorted(counts.items())),
        "labels_outside_owner_vocabulary": sorted(
            {row["owner_label"] for row in rows} - set(OWNER_EVIDENCE_CLASSES)
        ),
    }


def main(argv):
    if not argv:
        print(json.dumps({"status": "NO_ARGUMENTS"}))
        return 2
    print(json.dumps([audit(path) for path in argv], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
