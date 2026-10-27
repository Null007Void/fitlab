"""Public ``fitlab`` command: one small door in front of the accepted engine.

Three commands cover the release journey; each one delegates to the exact
bounded machinery that independent review accepted, and adds nothing else:

    fitlab inspect     environment, prerequisites and readiness (-> cli doctor)
    fitlab evaluate    the guarded local evaluation workflow (-> workflow run)
    fitlab passport    render/verify a Capability Passport (-> cli passport)

Deeper command surfaces stay available exactly as before:

    python -m fitlab_evaluation.cli plan|trust|passport|verify|gate|doctor
    python -m fitlab_evaluation.workflow run|postprocess

``evaluate`` invokes the existing guarded workflow unchanged: frozen task
pack, frozen grader, resource gates, no server start/stop, no model
load/download, no silent retries of failed model outputs. It performs
inference ONLY through the already-running local Lemonade runtime the
operator prepared; without one it fails fast with the runtime gate's own
error, by design.
"""

import argparse
import sys

from .artifacts import ArtifactError, BoundedParser, stable_json

EPILOG = """\
advanced surfaces:
  python -m fitlab_evaluation.cli plan|trust|passport|verify|gate|doctor
  python -m fitlab_evaluation.workflow run --output-dir DIR [--repeats N]
evidence classes: MEASURED CALCULATED ESTIMATED DECLARED UNSUPPORTED UNKNOWN UNAVAILABLE
"""


def _inspect(arguments):
    """Environment/prerequisite report: observed vs declared vs unavailable."""
    from .cli import _doctor

    return _doctor(arguments)


def _evaluate(arguments):
    """Hand the run to the accepted guarded workflow; add nothing, weaken nothing.

    The workflow keeps its own published output contract (single JSON line on
    stdout, machine-readable error JSON on stderr, exit 0/2) — the public
    entry proxies its exit code and prints nothing extra.
    """
    from .workflow import main as workflow_main

    argv = ["run", "--output-dir", str(arguments.output_dir),
            "--repeats", str(arguments.repeats)]
    if arguments.plan is not None:
        argv += ["--plan", str(arguments.plan)]
    if arguments.trust is not None:
        argv += ["--trust", str(arguments.trust)]
    return workflow_main(argv)


def _passport(arguments):
    from .cli import main as cli_main

    argv = ["passport", "--trust", str(arguments.trust),
            "--output-dir", str(arguments.output_dir)]
    if arguments.evaluation is not None:
        argv += ["--evaluation", str(arguments.evaluation)]
    if arguments.plan is not None:
        argv += ["--plan", str(arguments.plan)]
    return cli_main(argv)


def main(argv=None):
    parser = BoundedParser(
        description="FitLab — Local AI Capability Passport",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser(
        "inspect",
        help="Report host, runtime prerequisites and readiness "
             "(observed / calculated / estimated / declared / unavailable)",
    )
    inspect.add_argument("--commit", default="HEAD",
                         help="Source revision to identity-check (default HEAD)")

    evaluate = sub.add_parser(
        "evaluate",
        help="Run the guarded local evaluation against the prepared "
             "Lemonade runtime (inference happens here, only)",
    )
    evaluate.add_argument("--output-dir", type=str, required=True,
                          help="Fresh campaign directory (never overwritten)")
    evaluate.add_argument("--repeats", type=int, choices=(1, 2, 3), default=3,
                          help="Protocol repetitions: 3 = complete protocol")
    evaluate.add_argument("--plan", type=str, default=None,
                          help="Optional planning input JSON")
    evaluate.add_argument("--trust", type=str, default=None,
                          help="Optional trust snapshot (default: build from HEAD)")

    passport = sub.add_parser(
        "passport",
        help="Generate/verify the Capability Passport from accepted evidence",
    )
    passport.add_argument("--trust", type=str, required=True)
    passport.add_argument("--evaluation", type=str, default=None)
    passport.add_argument("--plan", type=str, default=None)
    passport.add_argument("--output-dir", type=str, required=True)

    arguments = parser.parse_args(argv)
    handlers = {"inspect": _inspect, "evaluate": _evaluate,
                "passport": _passport}
    try:
        # `evaluate` proxies the workflow's own exit contract: it has already
        # printed exactly one JSON line and returns 0/2 directly.
        code = handlers[arguments.command](arguments)
        if isinstance(code, int):
            return code
        print(stable_json(code), end="")
        return 0
    except ArtifactError as exc:
        code = exc.code
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError,
            UnicodeError):
        code = "INVALID_INPUT"
    except OSError:
        code = "IO_ERROR"
    print(stable_json({"status": "ERROR", "code": code}), end="",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())