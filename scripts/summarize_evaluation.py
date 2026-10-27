"""Summarize an evaluation record without trusting grep counts.

Read-only. Prints the top-level run facts, the row census and the declared
source identity so a report can bind numbers to evidence instead of to a
search hit count.

Usage:
    python scripts/summarize_evaluation.py <evaluation.json> [<evaluation.json> ...]
"""

import json
import sys
from collections import Counter
from pathlib import Path


def summarize(path):
    payload = json.loads(Path(path).read_text("utf-8"))
    rows = payload.get("rows") or []
    summary = payload.get("summary") or {}
    return {
        "artifact": str(Path(path).name),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "execution_kind": payload.get("execution_kind"),
        "requested_repeats": payload.get("requested_repeats"),
        "run_id": payload.get("run_id"),
        "rows": len(rows),
        "row_status_counts": dict(sorted(Counter(row.get("status") for row in rows).items())),
        "unique_case_ids": len({row.get("case_id") for row in rows}),
        "summary": {
            "planned_count": summary.get("planned_count"),
            "measured_count": summary.get("measured_count"),
            "passed_count": summary.get("passed_count"),
            "failed_or_unrun_count": summary.get("failed_or_unrun_count"),
            "median_client_latency_seconds": summary.get("median_client_latency_seconds"),
        },
        "source_sha256_files": len(payload.get("source_sha256") or {}),
        "task_pack_sha256": payload.get("task_pack_sha256"),
    }


def main(argv):
    if not argv:
        print(json.dumps({"status": "NO_ARGUMENTS"}))
        return 2
    print(json.dumps([summarize(path) for path in argv], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
