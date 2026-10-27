"""Local FitLab product CLI. Errors are bounded JSON; outputs are never overwritten.

DEPRECATED surface: the passport/report command here predates the v3
publication privacy boundary and is retained only for legacy callers. New
publications must go through fitlab_evaluation.report_v3.export_report
(fitlab passport / python -m fitlab_evaluation.cli passport), which enforces
redaction on every publication component and refuses unsanitized evidence.
"""
import argparse
from .artifacts import BoundedParser
import sys
from pathlib import Path
from .artifacts import ArtifactError,load_json,stable_json,publish_bundle
from .evidence import make_trust,validate_trust,verify_record
from .report import export_report


def main(argv=None):
    parser=BoundedParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    trust=sub.add_parser('trust');trust.add_argument('--commit',default='HEAD');trust.add_argument('--output-dir',type=Path,required=True)
    report=sub.add_parser('passport');report.add_argument('--trust',type=Path,required=True);report.add_argument('--evaluation',type=Path);report.add_argument('--plan',type=Path);report.add_argument('--output-dir',type=Path,required=True)
    check=sub.add_parser('verify');check.add_argument('--trust',type=Path,required=True);check.add_argument('--evaluation',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='trust':
            trust=make_trust(args.commit)
            # The trust bundle publishes trust.json verbatim: the
            # whole-trust privacy scan must refuse an unsanitized document
            # BEFORE publication, not only at later passport validation
            # (round-60 A-1 - a tracked filename could carry a private
            # fragment into source_sha256).
            validate_trust(trust)
            publish_bundle(args.output_dir,{'trust.json':stable_json(trust)})
        else:
            trust,_=load_json(args.trust)
            record=None if args.evaluation is None else load_json(args.evaluation)[0]
            if args.command=='verify':
                verified=verify_record(record,trust)
                print(stable_json({'status':'VERIFIED','run_status':verified['status'],'measurement_eligible':verified['measurement_eligible'],'complete_protocol':verified['complete_protocol']}),end='')
                return 0
            plan=None if args.plan is None else load_json(args.plan)[0]
            # The legacy exporter predates the publication privacy boundary
            # (round-25 review A-1). Rather than publish owner-controlled
            # content unredacted, refuse with a bounded migration error
            # directing every publication to the enforcing v3 exporter —
            # the same engine fitlab passport / cli passport already use.
            raise ArtifactError(
                "LEGACY_PASSPORT_WITHDRAWN_USE_V3_EXPORTER")
        print(stable_json({'status':'WRITTEN','artifact_kind':args.command}),end='')
        return 0
    except ArtifactError as exc:
        code=exc.code
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,UnicodeError):
        code='INVALID_INPUT'
    except OSError:
        code='IO_ERROR'
    print(stable_json({'status':'ERROR','code':code}),end='',file=sys.stderr)
    return 2

if __name__=='__main__':raise SystemExit(main())
