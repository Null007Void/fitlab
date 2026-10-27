"""Capability Passport v3: a shareable, honest, fully offline report.

Two audiences, one document:

* an everyday user who wants to know what their computer can run, what was
  actually shown, what failed and what is still unknown;
* a developer who needs the model and backend identity, the configuration and
  quantization, the formula versions, the frozen task definitions, the strict
  grader results, the resource telemetry, the evidence provenance and the
  reproduction commands.

Design rules enforced here:

* no measured value is ever invented. A missing measurement is rendered as an
  explicit unavailable state, never as zero and never as a pass;
* a synthetic record can never appear as a measurement;
* every number carries its evidence class, its basis and its limitation;
* the owner's five-class vocabulary is a presentation layer over the frozen
  machine classes: a stored class is never rewritten, and a synthetic or
  historical record is never presented as a measurement of this build;
* the document is fully self-contained: no scripts, no remote fonts, no
  network references, no analytics;
* every string that reaches the page is escaped, and private detail such as
  local paths, user names, e-mail addresses and network addresses is removed
  before rendering.
"""

import html
import json
from pathlib import Path

from .artifacts import ArtifactError, digest, stable_json, publish_bundle, source_digest
from .evidence import validate_trust, verify_record, source_binding
from .grader import exact_equal
from .redact import (
    contains_private_detail,
    redact_structure,
    redact_text,
    redact_value,
    redact_with_distinct_identities,
)
from fitlab_foundation.planner_cli import run_document
from fitlab_foundation.serialization import to_primitive

SCHEMA_VERSION = "fitlab-capability-passport-v3"

# Evidence classes, most to least certain. The rendering styles them.
MEASURED = "MEASURED"
ESTIMATED = "ESTIMATED"
CALCULATED = "CALCULATED"
DECLARED = "DECLARED"
UNSUPPORTED = "UNSUPPORTED"
UNKNOWN = "UNKNOWN"

_EVIDENCE_CLASSES = {MEASURED, ESTIMATED, CALCULATED, DECLARED, UNSUPPORTED, UNKNOWN}

# The owner's five-class vocabulary is a presentation layer over the frozen
# machine classes above. It never rewrites a stored class and never upgrades a
# value: the raw class stays the machine-readable fact, the label is what a
# reader sees.
ANALYTICAL_ESTIMATE = "ANALYTICAL ESTIMATE"
SYNTHETIC_TEST_EVIDENCE = "SYNTHETIC TEST EVIDENCE"
HISTORICAL_MEASURED_EVIDENCE = "HISTORICAL MEASURED EVIDENCE"

OWNER_EVIDENCE_CLASSES = (
    MEASURED,
    ANALYTICAL_ESTIMATE,
    SYNTHETIC_TEST_EVIDENCE,
    HISTORICAL_MEASURED_EVIDENCE,
    UNKNOWN,
)

_ANALYTICAL_CLASSES = {ESTIMATED, CALCULATED, DECLARED}
_HISTORICAL_KEYS = {
    "campaign_id",
    "request_count",
    "source_commit",
    "source_tree",
    "delivery_sha256",
    "note",
}


def evidence_label(kind, *, execution_kind=None, historical=False):
    """Present one machine evidence class in the owner's vocabulary.

    MEASURED and UNKNOWN pass through unchanged. A measured value is presented
    as SYNTHETIC TEST EVIDENCE when the record itself declares a synthetic
    harness, and as HISTORICAL MEASURED EVIDENCE only when the caller binds it
    to an earlier campaign; synthetic wins over historical so a harness record
    can never be presented as measured. ESTIMATED, CALCULATED and DECLARED are
    all analytical derivations. UNSUPPORTED carries no value at all, so it
    presents as UNKNOWN while its reason stays in the limitation text.
    """
    if kind == MEASURED:
        if execution_kind == "SYNTHETIC_TEST":
            return SYNTHETIC_TEST_EVIDENCE
        if historical:
            return HISTORICAL_MEASURED_EVIDENCE
        return MEASURED
    if kind == UNKNOWN:
        return UNKNOWN
    if kind in _ANALYTICAL_CLASSES:
        return ANALYTICAL_ESTIMATE
    if kind == UNSUPPORTED:
        return UNKNOWN
    raise ArtifactError("INVALID_EVIDENCE_CLASS")


def evaluation_label(verified, historical=False):
    """Present what the whole report demonstrated, in the same vocabulary."""
    if verified is not None and verified["execution_kind"] == "SYNTHETIC_TEST":
        return SYNTHETIC_TEST_EVIDENCE
    if historical:
        return HISTORICAL_MEASURED_EVIDENCE
    if verified is None:
        return UNKNOWN
    return MEASURED if verified["measurement_eligible"] else UNKNOWN


def _validate_historical(binding):
    """Accept only a fully identified earlier campaign, or nothing at all."""
    if binding is None:
        return None
    if type(binding) is not dict or set(binding) != _HISTORICAL_KEYS:
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    campaign = binding["campaign_id"]
    requests = binding["request_count"]
    commit = binding["source_commit"]
    tree = binding["source_tree"]
    delivery = binding["delivery_sha256"]
    note = binding["note"]
    if type(campaign) is not str or not 0 < len(campaign) <= 200:
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    if type(requests) is not int or isinstance(requests, bool) or not 0 < requests <= 100000:
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    if type(commit) is not str or len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    if type(tree) is not str or len(tree) != 40 or not all(c in "0123456789abcdef" for c in tree):
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    if type(delivery) is not str or len(delivery) != 64 or not all(c in "0123456789abcdef" for c in delivery):
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    if type(note) is not str or not 0 < len(note) <= 512:
        raise ArtifactError("INVALID_HISTORICAL_BINDING")
    # HISTORICAL MEASURED EVIDENCE is a strong claim: shape validity alone
    # does not make a synthetic campaign identifier "measured" (round-28
    # A-2). The binding is accepted as an identified DECLARATION of an
    # earlier campaign; the measured class is assigned ONLY with a verified
    # LOCAL_RUNTIME record whose source binding matches the campaign's
    # source identity, or when the caller separately vouches (the
    # acceptance-lane path). Without that corroboration the metadata is
    # presented as DECLARED (an assertion, not a measurement).
    return {
        "campaign_id": campaign,
        "request_count": requests,
        "source_commit": commit,
        "source_tree": tree,
        "delivery_sha256": delivery,
        "note": note,
        "evidence_class": DECLARED,
        "evidence_label": evidence_label(DECLARED),
        "evidence_corroborated": False,
    }


def _corroborate_historical(binding, verified):
    """Promote a historical binding to MEASURED only with matching verified
    LOCAL_RUNTIME evidence bound to the same source identity."""
    if binding is None or verified is None:
        return binding
    record = verified.get("_record") if isinstance(verified, dict) else None
    if record is None:
        return binding
    if record.get("execution_kind") != "LOCAL_RUNTIME":
        return binding
    sources = record.get("source_sha256")
    if type(sources) is not dict:
        return binding
    normalized = {k.replace("\\", "/"): v for k, v in sources.items()}
    if normalized.get("fitlab_evaluation/run.py") is None:
        return binding
    binding = dict(binding)
    binding["evidence_class"] = MEASURED
    binding["evidence_label"] = evidence_label(MEASURED, historical=True)
    binding["evidence_corroborated"] = True
    return binding

# The task tiers, used to separate the R2 core requirement from the
# supplemental cases without ever changing a frozen grading criterion.
TASK_TIERS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "task-tiers.json"


def _load_tiers(trust):
    try:
        raw = TASK_TIERS_PATH.read_bytes()
        expected = trust["source_sha256"].get("fixtures/task-tiers.json")
        if type(expected) is not str or source_digest(raw) != expected:
            raise ArtifactError("TASK_TIERS_SOURCE_MISMATCH")
        payload = json.loads(raw.decode("utf-8"))
    except ArtifactError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ArtifactError("TASK_TIERS_UNAVAILABLE") from exc
    if type(payload) is not dict or payload.get("schema_version") != "fitlab-task-tiers-v1":
        raise ArtifactError("TASK_TIERS_UNAVAILABLE")
    return payload


def _tier_of(tiers, case_id):
    for name in ("core", "supplemental"):
        if case_id in tiers["tiers"][name]["case_ids"]:
            return name
    raise ArtifactError("TASK_TIER_UNCLASSIFIED")


def _core_counts(summary, tiers):
    """Aggregate the R2 core tier from the per-case summary.

    The core denominator is fixed by the approved R2 baseline: six core cases
    with three measured repetitions each. Supplemental observations never
    count toward it, and a partial run never shrinks it.
    """
    core_ids = tiers["tiers"]["core"]["case_ids"]
    passed = 0
    observed = 0
    for case_id in core_ids:
        counts = summary["by_case"][case_id]
        passed += counts["passed_count"]
        observed += counts["measured_count"]
    return {
        "passed": passed,
        "planned": tiers["denominator_policy"]["core_denominator"],
        "observed": observed,
    }


def build_report(trust, record=None, plan=None, advisory=None, provenance=None, host=None, historical=None):
    """Build the report from verified evidence only."""
    pack = validate_trust(trust)
    verified = None if record is None else verify_record(record, trust)
    if record is not None and plan is not None:
        if any(s["model"]["model_id"] != record["model"] for s in plan.get("scenarios", [])):
            raise ArtifactError("PLANNING_MODEL_MISMATCH")
        if record["planning_input"] is not None and not exact_equal(plan, record["planning_input"]):
            raise ArtifactError("PLANNING_OVERRIDE_FORBIDDEN")
    # A standalone owner plan is sanitized with the collision-safe identity
    # allocator BEFORE use: planning math runs on the sanitized copy, so the
    # report, its claims and the stored planning input are all mutually
    # consistent and the input replays through the planner byte-exact as
    # stored.
    stored_plan_input = None
    if plan is not None:
        stored_plan_input, _ = redact_with_distinct_identities(to_primitive(plan))
    planning_input = (
        stored_plan_input
        if plan is not None
        else (None if record is None else record["planning_input"])
    )
    planning = (
        None
        if stored_plan_input is None
        else to_primitive(run_document(stored_plan_input))
    )
    if planning is None and verified is not None:
        planning = verified["planning_output"]
    eligible = verified is not None and verified["measurement_eligible"]
    summary = None if verified is None else verified["summary"]
    state = (
        "NO_EVIDENCE"
        if verified is None
        else ("SYNTHETIC_ONLY" if verified["execution_kind"] == "SYNTHETIC_TEST" else verified["status"])
    )
    tiers = _load_tiers(trust)
    record_kind = None if verified is None else verified["execution_kind"]
    historical_campaign = _validate_historical(historical)
    # Measured promotion requires corroborating verified LOCAL_RUNTIME
    # evidence bound to the same source identity (round-28 A-2). The
    # verified mapping carries the source binding; a historical declaration
    # without corroboration stays DECLARED.
    if historical_campaign is not None and verified is not None \
            and verified.get("execution_kind") == "LOCAL_RUNTIME" \
            and verified["source_binding"]["commit"] == historical_campaign["source_commit"] \
            and verified["source_binding"]["tree"] == historical_campaign["source_tree"]:
        historical_campaign = dict(historical_campaign)
        historical_campaign["evidence_class"] = MEASURED
        historical_campaign["evidence_label"] = evidence_label(
            MEASURED, historical=True)
        historical_campaign["evidence_corroborated"] = True

    claims = []

    def claim(identifier, label, kind, value, unit, basis, limitation):
        if kind not in _EVIDENCE_CLASSES:
            raise ArtifactError("INVALID_EVIDENCE_CLASS")
        claims.append(
            {
                "id": identifier,
                "label": label,
                "evidence_class": kind,
                "evidence_label": evidence_label(kind, execution_kind=record_kind),
                "value": value,
                "unit": unit,
                "basis": basis,
                "limitation": limitation,
            }
        )

    claim(
        "tasks",
        "Task outcomes",
        MEASURED if eligible else UNKNOWN,
        {
            "passed": summary["passed_count"],
            "planned": summary["planned_count"],
            "observed": summary["measured_count"],
        }
        if eligible
        else None,
        "cases",
        ["evaluation:rows"] if eligible else [],
        "Known toy tasks; no held-out general capability or reliability claim.",
    )
    claim(
        "core_tasks",
        "Core task outcomes (R2 baseline)",
        MEASURED if eligible else UNKNOWN,
        _core_counts(summary, tiers) if eligible else None,
        "cases",
        ["evaluation:rows", "fixtures/task-tiers.json"] if eligible else [],
        "Six core cases x three measured repetitions. Supplemental cases do not satisfy this denominator.",
    )
    claim(
        "latency",
        "Client latency, median",
        MEASURED if eligible else UNKNOWN,
        summary["median_client_latency_seconds"] if eligible else None,
        "seconds",
        ["evaluation:rows.elapsed_seconds"] if eligible else [],
        "End-to-end nonstreaming latency, not decode throughput; cache state unknown.",
    )
    for identifier, label, unit in (
        ("peak_ram", "Model peak RAM", "bytes"),
        ("ttft", "Time to first token", "seconds"),
        ("decode", "Decode throughput", "tokens/s"),
    ):
        claim(
            identifier,
            label,
            UNKNOWN,
            None,
            unit,
            [],
            "Not collected by this protocol; null never means zero.",
        )

    if planning is not None:
        models = {s["scenario_id"]: s["model"]["model_id"] for s in planning_input["scenarios"]}
        for row in planning["results"]:
            workload = row.get("workload_plan", row)
            for key, result in sorted(workload["requirements"].items()):
                if type(result) is not dict or "status" not in result:
                    continue
                reasons = result.get("reasons", [])
                unsupported = any("UNSUPPORTED" in x["code"] for x in reasons)
                if unsupported:
                    kind = UNSUPPORTED
                elif result["status"] in ("CALCULATED", "ESTIMATED"):
                    kind = result["status"]
                else:
                    kind = UNKNOWN
                claim(
                    "plan:" + row["scenario_id"] + ":" + key,
                    row["scenario_id"] + " · " + models[row["scenario_id"]] + " · " + key.replace("_", " ").capitalize(),
                    kind,
                    result["value"],
                    result["unit"],
                    ["planning:" + row["scenario_id"] + ":" + key],
                    "; ".join(result["limitations"] + [r["detail"] for r in reasons])
                    or "Derived from declared inputs, not a hardware measurement.",
                )

    tasks = []
    for case in pack["cases"]:
        counts = summary["by_case"][case["id"]] if eligible else None
        tier = _tier_of(tiers, case["id"])
        tasks.append(
            {
                "id": case["id"],
                "category": case["category"],
                "tier": tier,
                "observed": None if counts is None else counts["measured_count"],
                "passed": None if counts is None else counts["passed_count"],
                "planned": None if summary is None else summary["by_case"][case["id"]]["planned_count"],
                "evidence_class": MEASURED if counts and counts["measured_count"] else UNKNOWN,
                "evidence_label": evidence_label(
                    MEASURED if counts and counts["measured_count"] else UNKNOWN,
                    execution_kind=record_kind,
                ),
            }
        )

    return redact_value({
        "schema_version": SCHEMA_VERSION,
        "title": "Lemonade FitLab",
        "source": {
            "binding": source_binding(),
            "commit": trust["source_commit"],
            "tree": trust["source_tree"],
            "trust_sha256": digest(stable_json(trust).encode()),
            "task_pack_sha256": trust["task_pack_sha256"],
            "evaluation_sha256": None if record is None else digest(stable_json(record).encode()),
            "planning_sha256": None if planning_input is None else digest(stable_json(planning_input).encode()),
        },
        "evaluation_state": state,
        "capability_verdict": "OBSERVED_TOY_TASKS_ONLY" if eligible else "NOT_EVALUATED",
        "evidence_class": evaluation_label(verified, historical=historical_campaign is not None),
        "evidence_class_vocabulary": {
            "owner": list(OWNER_EVIDENCE_CLASSES),
            "machine": sorted(_EVIDENCE_CLASSES),
            "analytical_estimate_from": sorted(_ANALYTICAL_CLASSES),
            "unchanged": [MEASURED, UNKNOWN],
            "unsupported_presents_as": UNKNOWN,
        },
        "historical_campaign": historical_campaign,
        "complete_protocol": False if verified is None else verified["complete_protocol"] and eligible,
        "claims": claims,
        "tasks": tasks,
        "planning": planning,
        "planning_provenance": provenance,
        "memory_advisory": advisory,
        "host": host,
        "task_tiers": {
            "core": tiers["tiers"]["core"],
            "supplemental": tiers["tiers"]["supplemental"],
            "denominator_policy": tiers["denominator_policy"],
            "approval_status": tiers["provenance"]["approval_status"],
        },
        "provenance_limit": "Source/hash consistency and grades verified; execution origin is declared, not cryptographically authenticated.",
        "limitations": [
            "Software tests and synthetic records never establish measured model capability.",
            "A stopped or interrupted run retains its declared full denominator; unrun cases are not successes.",
            "Calculated and estimated values use supplied planning assumptions and do not establish real hardware fit.",
            "No TTFT, model peak RAM, cold-load performance or statistical reliability is measured.",
            "A hybrid short-convolution architecture is not modelled by the shared requirements engine, so its cache and memory baseline remain unknown.",
        ],
    })


def _escape(value):
    return html.escape(str(value), quote=True)


def _bytes(value):
    if value is None:
        return None
    number = int(value)
    if number >= (1 << 30):
        return f"{number / (1 << 30):.2f} GiB"
    if number >= (1 << 20):
        return f"{number / (1 << 20):.2f} MiB"
    if number >= 1024:
        return f"{number / 1024:.2f} KiB"
    return f"{number} B"


def _label_kind(label):
    """CSS token for one owner label, from a fixed map rather than free text."""
    return {
        MEASURED: "measured",
        ANALYTICAL_ESTIMATE: "estimated",
        SYNTHETIC_TEST_EVIDENCE: "declared",
        HISTORICAL_MEASURED_EVIDENCE: "historical",
        UNKNOWN: "unknown",
    }.get(label, "unknown")


def _render_html(report):
    esc = _escape
    text = redact_text

    def value_text(value):
        if value is None:
            return "Unavailable"
        if type(value) is dict:
            return (
                f"{value['passed']} of {value['planned']} planned"
                f" · {value['observed']} observed"
            )
        return str(value)

    # ---- Everyday-user summary -------------------------------------------
    state_label = report["evaluation_state"].replace("_", " ")
    verdict = report["capability_verdict"]
    if verdict == "NOT_EVALUATED":
        headline = "No model capability has been measured yet."
        detail = (
            "This report records the completed planning and verification checks "
            "listed below; no model capability has been measured, so it makes no "
            "claim about how this model runs on this machine."
        )
    else:
        headline = "Measured outcomes exist for a fixed toy-task suite."
        detail = (
            "These outcomes apply to eight known test cases under one declared configuration. "
            "They are not a general capability certification."
        )

    host = report.get("host") or {}
    host_rows = []
    if host.get("total_physical_bytes"):
        host_rows.append(("Memory installed", _bytes(host["total_physical_bytes"])))
    if host.get("cpu_brand"):
        host_rows.append(("Processor", host["cpu_brand"]))
    if host.get("logical_processors"):
        host_rows.append(("Logical processors", str(host["logical_processors"])))
    if host.get("accelerator"):
        host_rows.append(("Accelerator", host["accelerator"]))
    host_block = (
        "<dl class=\"kv\">"
        + "".join(
            f"<dt>{esc(text(k))}</dt><dd>{esc(text(v))}</dd>" for k, v in host_rows
        )
        + "</dl>"
        if host_rows
        else "<p class=\"muted\">Host details were not recorded for this report.</p>"
    )

    provenance = report.get("planning_provenance") or {}
    model_rows = []
    if provenance.get("model_id"):
        # An unverified header identity is disclosed, never silently styled
        # as the frozen contract checkpoint.
        suffix = (" (unverified header identity)"
                  if provenance.get("model_identity") == "UNVERIFIED" else "")
        model_rows.append(("Model", provenance["model_id"] + suffix))
    if provenance.get("checkpoint"):
        model_rows.append(("Checkpoint", provenance["checkpoint"]))
    if provenance.get("quantization"):
        model_rows.append(("Quantization", provenance["quantization"]))
    if provenance.get("total_parameters"):
        model_rows.append(("Parameters", f"{int(provenance['total_parameters']):,}"))
    if provenance.get("architecture_family"):
        model_rows.append(("Architecture", provenance["architecture_family"]))
    if provenance.get("hybrid"):
        model_rows.append(
            (
                "Attention",
                f"hybrid short-convolution + attention "
                f"({provenance.get('convolution_block_count', '?')} conv blocks, "
                f"{provenance.get('attention_block_count', '?')} attention blocks)",
            )
        )
    if provenance.get("context_length"):
        model_rows.append(("Trained context length", f"{int(provenance['context_length']):,} tokens"))
    if provenance.get("runtime_version"):
        model_rows.append(("Runtime version", provenance["runtime_version"]))
    model_block = (
        "<dl class=\"kv\">"
        + "".join(f"<dt>{esc(text(k))}</dt><dd>{esc(text(v))}</dd>" for k, v in model_rows)
        + "</dl>"
        if model_rows
        else "<p class=\"muted\">No model identity was supplied for this report.</p>"
    )

    # Planning feasibility, in plain language.
    feasibility = []
    for claim in report["claims"]:
        if not claim["id"].startswith("plan:"):
            continue
        if claim["evidence_class"] == UNSUPPORTED:
            verdict_text = "Not supported by the engine for this architecture"
        elif claim["evidence_class"] in (CALCULATED, ESTIMATED):
            verdict_text = "A computed estimate from declared inputs"
        else:
            verdict_text = "Unknown"
        feasibility.append(
            f"<tr><th>{esc(text(claim['label']))}</th>"
            f"<td><span class=\"kind {_label_kind(claim['evidence_label'])}\">{esc(claim['evidence_label'])}</span></td>"
            f"<td>{esc(text(claim['value']) if claim['value'] is not None else 'Unavailable')}"
            f"{' ' + esc(text(claim['unit'])) if claim['unit'] else ''}</td>"
            f"<td class=\"lim\">{esc(text(verdict_text))}</td></tr>"
        )
    feasibility_block = (
        "<div class=\"tablewrap\"><table><thead><tr><th>Requirement</th><th>Evidence</th>"
        "<th>Value</th><th>What it means</th></tr></thead><tbody>"
        + "".join(feasibility)
        + "</tbody></table></div>"
        if feasibility
        else "<p class=\"muted\">No planning input was supplied, so hardware fit is unknown.</p>"
    )

    advisory = report.get("memory_advisory")
    advisory_block = ""
    if advisory:
        rows = "".join(
            f"<tr><th>{esc(text(c['component'].replace('_', ' ')))}</th>"
            f"<td><span class=\"kind {'measured' if c['evidence'] == 'CALCULATED' else 'estimated'}\">"
            f"{esc(c['evidence'] if c['evidence'] in ('CALCULATED', 'ESTIMATED', 'DECLARED', 'UNSUPPORTED') else 'UNVERIFIED')}</span></td>"
            f"<td>{esc(_bytes(c['bytes']))}</td>"
            f"<td class=\"lim\">{esc(text(c['limitation']))}</td></tr>"
            for c in advisory["components"]
        )
        advisory_block = (
            "<section><h2>Memory advisory</h2>"
            "<p class=\"muted\">A disclosed composite estimate for this hybrid architecture. "
            "The shared requirements engine returns <code>UNKNOWN</code> for the model&rsquo;s memory "
            "baseline because it does not model short-convolution state, and that engine result is "
            "unchanged by this advisory.</p>"
            f"<p><strong>Total estimate: {esc(_bytes(advisory['bytes']))}</strong> "
            "&mdash; an estimate over declared inputs, not a measurement.</p>"
            "<div class=\"tablewrap\"><table><thead><tr><th>Component</th><th>Evidence</th>"
            f"<th>Size</th><th>Limit</th></tr></thead><tbody>{rows}</tbody></table></div></section>"
        )

    historical = report.get("historical_campaign")
    historical_block = ""
    if historical:
        historical_block = (
            "<section><h2>4b. Earlier measured campaign bound to this report</h2>"
            "<p class=\"muted\">These results were measured in an earlier campaign by the code at the "
            "commit below. They are not evidence produced by this build, and they are never relabelled "
            "as if they were.</p>"
            "<dl class=\"kv\">"
            f"<dt>Evidence</dt><dd><span class=\"kind historical\">{esc(historical['evidence_label'])}</span></dd>"
            f"<dt>Campaign</dt><dd>{esc(text(historical['campaign_id']))}</dd>"
            f"<dt>Requests</dt><dd>{int(historical['request_count'])}</dd>"
            f"<dt>Source commit</dt><dd><code>{esc(historical['source_commit'])}</code></dd>"
            f"<dt>Source tree</dt><dd><code>{esc(historical['source_tree'])}</code></dd>"
            f"<dt>Delivery SHA-256</dt><dd><code>{esc(historical['delivery_sha256'])}</code></dd>"
            f"<dt>Note</dt><dd>{esc(text(historical['note']))}</dd></dl></section>"
        )

    # ---- Developer section ------------------------------------------------
    source = report["source"]
    developer_rows = "".join(
        f"<tr><th>{esc(text(k))}</th><td><code>{esc(text(v))}</code></td></tr>"
        for k, v in (
            ("Source commit", source["commit"]),
            ("Source tree", source["tree"]),
            ("Source binding", source["binding"]),
            ("Trust snapshot SHA-256", source["trust_sha256"]),
            ("Task pack SHA-256", source["task_pack_sha256"]),
            ("Evaluation SHA-256", source["evaluation_sha256"] or "none"),
            ("Planning input SHA-256", source["planning_sha256"] or "none"),
        )
    )

    task_rows = "".join(
        f"<tr><th>{esc(t['id'])}</th>"
        f"<td>{esc(t['category'].replace('_', ' '))}</td>"
        f"<td><span class=\"kind {('core' if t['tier'] == 'core' else 'supplemental')}\">{esc(t['tier'])}</span></td>"
        f"<td><span class=\"kind {_label_kind(t['evidence_label'])}\">"
        f"{esc(t['evidence_label'])}</span></td>"
        f"<td>{esc('Unavailable' if t['observed'] is None else str(t['passed']) + ' / ' + str(t['planned']) + ' planned; ' + str(t['observed']) + ' observed')}</td></tr>"
        for t in report["tasks"]
    )

    provenance_items = "".join(
        f"<li>{esc(text(x))}</li>" for x in report["limitations"]
    )

    # Placeholders are written raw here and escaped once by esc() below;
    # planning input and the passport output are distinct directories
    # (publication is atomic and never overwrites).
    repro_steps = [
        "python -m fitlab_evaluation.cli doctor",
        "python -m fitlab_evaluation.cli plan workload_to_hardware --output-dir <plan-dir>",
        "python -m fitlab_evaluation.cli trust --output-dir <trust-dir>",
        "python -m fitlab_evaluation.cli passport --trust <trust-dir>/trust.json --output-dir <passport-dir>",
    ]
    repro = "".join(f"<li><code>{esc(step)}</code></li>" for step in repro_steps)

    cards = "".join(
        f"<article class=\"metric\"><div class=\"kind {_label_kind(c['evidence_label'])}\">"
        f"{esc(c['evidence_label'])}</div><h3>{esc(text(c['label']))}</h3>"
        f"<strong>{esc(text(value_text(c['value'])))}</strong>"
        f"<small>{esc(text(c['unit'] or ''))}</small>"
        f"<p>{esc(text(c['limitation']))}</p></article>"
        for c in report["claims"][:6]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; img-src 'none'; script-src 'none'">
<title>Lemonade FitLab &mdash; Capability Passport</title>
<style>
:root{{color-scheme:light;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#14342c;background:#f4f7f1;--line:#d6e0d0;--ink:#14342c;--muted:#55685b;--panel:#ffffff}}
*{{box-sizing:border-box}}
body{{max-width:1120px;margin:0 auto;padding:40px 24px 64px;line-height:1.55;font-size:16px}}
header{{display:flex;justify-content:space-between;align-items:center;gap:24px;border-bottom:3px solid var(--ink);padding-bottom:26px;margin-bottom:8px}}
.eyebrow{{letter-spacing:.16em;text-transform:uppercase;font-size:.72rem;font-weight:700;color:var(--muted)}}
h1{{font-size:clamp(2rem,5vw,3.4rem);line-height:1.04;margin:10px 0 6px}}
h2{{font-size:1.3rem;margin:0 0 10px}}
h3{{font-size:.95rem;margin:8px 0 4px}}
.lede{{color:var(--muted);margin:0;max-width:62ch}}
.seal{{border:2px solid var(--ink);border-radius:14px;padding:16px 20px;text-align:center;font-weight:800;background:#ddeb98;min-width:150px;font-size:.9rem;letter-spacing:.06em}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;margin:22px 0}}
.verdict{{border-left:5px solid #b67c08;background:#fff6d9;padding:18px 22px;margin:22px 0;border-radius:0 10px 10px 0}}
.verdict.measured{{border-left-color:#3d7a37;background:#e6f4e2}}
.verdict h2{{margin-bottom:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}}
.metric{{background:#f7faf5;border:1px solid var(--line);border-radius:12px;padding:18px;min-width:0}}
.metric strong{{font-size:1.15rem;display:block;overflow-wrap:anywhere}}
.metric small{{color:var(--muted)}}
.metric p{{font-size:.78rem;color:var(--muted);margin:.4rem 0 0}}
.kind{{display:inline-block;font-size:.63rem;letter-spacing:.08em;font-weight:800;padding:3px 7px;border-radius:4px;background:#e8ece3;white-space:nowrap}}
.measured{{background:#d6ecc3;color:#2c5e28}}
.estimated,.calculated{{background:#fdeec0;color:#7a5a06}}
.declared{{background:#d9e6f5;color:#274a75}}
.historical{{background:#d9e6f5;color:#274a75}}
.unsupported{{background:#f7d9cc;color:#8a3418}}
.unknown{{background:#e8ece3;color:#4a5a4e}}
.core{{background:#cfe3d4;color:#22512f}}
.supplemental{{background:#e4e8ee;color:#3f4a5c}}
.legend{{display:flex;flex-wrap:wrap;gap:10px;font-size:.78rem;margin:14px 0 0}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
th,td{{padding:10px 8px;border-bottom:1px solid #e4eae0;text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{font-weight:600;width:26%}}
td.lim{{color:var(--muted);font-size:.8rem;width:34%}}
.tablewrap{{overflow-x:auto}}
code{{font-size:.78rem;overflow-wrap:anywhere;background:#f1f4ee;padding:1px 4px;border-radius:3px}}
ul{{padding-left:20px}}
li{{margin:.25rem 0}}
.kv{{display:grid;grid-template-columns:minmax(150px,auto) 1fr;gap:6px 18px;margin:0;font-size:.9rem}}
.kv dt{{font-weight:600;color:var(--muted)}}
.kv dd{{margin:0;overflow-wrap:anywhere}}
.muted{{color:var(--muted);font-size:.88rem}}
footer{{margin-top:30px;font-size:.8rem;color:var(--muted);border-top:1px solid var(--line);padding-top:16px}}
@media(max-width:680px){{body{{padding:24px 14px}}header{{flex-direction:column;align-items:flex-start}}section{{padding:16px}}th{{width:auto}}.kv{{grid-template-columns:1fr}}}}
@media print{{body{{max-width:none;padding:0}}section{{break-inside:avoid;border-color:#999}}}}
</style></head>
<body>
<header>
<div><div class="eyebrow">Local AI &middot; evidence before claims</div>
<h1>Capability Passport</h1>
<p class="lede">Lemonade FitLab &mdash; what was assessed, what was actually shown, what failed, and what is still unknown.</p></div>
<div class="seal">FITLAB<br><small>OFFLINE REPORT</small></div>
</header>

<div class="verdict{' measured' if report['capability_verdict'] != 'NOT_EVALUATED' else ''}">
<h2>{esc(headline)}</h2>
<p>{esc(detail)}</p>
<p class="muted" style="margin:.4rem 0 0">Evaluation state: <strong>{esc(state_label)}</strong> &middot; Capability verdict: <strong>{esc(verdict.replace('_', ' '))}</strong> &middot; Complete three-round protocol: <strong>{'yes' if report['complete_protocol'] else 'no'}</strong> &middot; Evidence class: <strong>{esc(report['evidence_class'])}</strong></p>
</div>

<section><h2>1. What your computer is</h2>
<p class="muted">The hardware this assessment targeted.</p>
{host_block}
</section>

<section><h2>2. What was evaluated</h2>
<p class="muted">The model and workload behind the numbers.</p>
{model_block}
</section>

<section><h2>3. Is a resource estimate plausible or constrained?</h2>
<p class="muted">Every value below is computed from declared inputs by the shared requirements engine. None of it is a hardware measurement.</p>
{feasibility_block}
{advisory_block}
</section>

<section><h2>4. What was actually demonstrated</h2>
<div class="grid">{cards}</div>
<div class="legend"><span class="kind measured">Measured</span><span class="kind estimated">Analytical estimate</span><span class="kind declared">Synthetic test evidence</span><span class="kind historical">Historical measured evidence</span><span class="kind unknown">Unknown</span></div>
</section>

{historical_block}

<section><h2>5. Task capability ledger</h2>
<p class="muted">Eight frozen test cases. A missing result is unavailable, never zero latency and never a pass.</p>
<div class="tablewrap"><table><thead><tr><th>Task</th><th>Scope</th><th>Tier</th><th>Evidence</th><th>Outcome</th></tr></thead><tbody>{task_rows}</tbody></table></div>
</section>

<section><h2>6. What failed, and what remains unknown</h2>
<ul>{provenance_items}</ul>
<p class="muted">A stopped or interrupted run keeps its full planned denominator. Unrun cases are never counted as successes.</p>
</section>

<section><h2>7. Developer: provenance and reproducibility</h2>
<div class="tablewrap"><table><tbody>{developer_rows}</tbody></table></div>
<p class="muted" style="margin-top:14px">{esc(text(report['provenance_limit']))}</p>
</section>

<section><h2>8. Developer: reproduction</h2>
<p class="muted">Every command is offline. Use a new output directory each time; existing directories are never overwritten.</p>
<ol>{repro}</ol>
</section>

<footer>Self-contained offline report &mdash; no scripts, no remote fonts, no analytics, no network references. Measured values exist only where a verified local-runtime run produced them. Public release and competition submission remain owner-controlled and have not been performed.</footer>
</body></html>
"""


def render_report(report, trust, record=None, plan=None, advisory=None, provenance=None, host=None, historical=None):
    """Render the report. A forged report dict cannot add observations."""
    expected = build_report(trust, record, plan, advisory, provenance, host, historical)
    if not exact_equal(report, expected):
        raise ArtifactError("REPORT_MISMATCH")
    return _render_html(report)


def export_report(directory, trust, record=None, plan=None, advisory=None, provenance=None, host=None, historical=None):
    """Publish a complete, atomic report bundle. Never overwrites."""
    # The privacy boundary is enforced at PUBLICATION time, not only at
    # evaluation time: an imported record may still verify cryptographically
    # (its hashes bind the bytes that were written) while predating a
    # redaction rule. Such a record must not reach the shareable bundle in
    # its raw form, and silently rewriting verified evidence is not allowed
    # either — so an unsanitized record FAILS the export instead. The scan
    # walks the DECODED string values recursively (a json.dumps scan would
    # miss non-ASCII payloads like "user@\u00e9xample.org"; a bare dict
    # argument would scan nothing at all).
    if record is not None:
        _private_hits = []

        def _scan(value):
            if contains_private_detail(value):
                _private_hits.append(True)
            return value

        redact_structure(record, _scan)
        if _private_hits:
            raise ArtifactError("EVALUATION_RECORD_NOT_SANITIZED")
    report = build_report(trust, record, plan, advisory, provenance, host, historical)
    rendered = render_report(report, trust, record, plan, advisory, provenance, host, historical)
    files = {
        "passport.json": stable_json(report),
        "passport.html": rendered,
        "trust.json": stable_json(trust),
    }
    if record is not None:
        files["evaluation.json"] = stable_json(record)
    # The stored planning input is written exactly as the report consumed
    # it: standalone plans arrive through the collision-safe identity
    # allocator, record copies were already sanitized at evaluation time. No
    # second redaction pass, or the published file would diverge from the
    # report's own input.
    planning_input = (
        redact_with_distinct_identities(to_primitive(plan))[0]
        if plan is not None
        else (None if record is None else record["planning_input"])
    )
    # Publication copies of owner-supplied companion artifacts pass through
    # the same redaction engine as the report: declarations may innocently
    # carry local paths, usernames or host names, and the bundle is the
    # shareable component.
    if planning_input is not None:
        files["planning-input.json"] = stable_json(planning_input)
    if advisory is not None:
        files["memory-advisory.json"] = stable_json(redact_value(advisory))
    if provenance is not None:
        files["planning-provenance.json"] = stable_json(redact_value(provenance))
    if host is not None:
        # The companion must satisfy the same privacy contract as the
        # rendered report: owner-supplied host values may carry local paths,
        # emails or endpoints.
        files["host-identity.json"] = stable_json(redact_value(host))
    return publish_bundle(directory, files)
