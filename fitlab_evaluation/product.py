"""Local FitLab product CLI. Errors are bounded JSON; outputs are never overwritten."""
import argparse
from .artifacts import BoundedParser
import sys
from pathlib import Path
from .artifacts import ArtifactError,load_json,stable_json,publish_bundle
from .evidence import make_trust,verify_record
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
            publish_bundle(args.output_dir,{'trust.json':stable_json(make_trust(args.commit))})
        else:
            trust,_=load_json(args.trust)
            record=None if args.evaluation is None else load_json(args.evaluation)[0]
            if args.command=='verify':
                verified=verify_record(record,trust)
                print(stable_json({'status':'VERIFIED','run_status':verified['status'],'measurement_eligible':verified['measurement_eligible'],'complete_protocol':verified['complete_protocol']}),end='')
                return 0
            plan=None if args.plan is None else load_json(args.plan)[0]
            export_report(args.output_dir,trust,record,plan)
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
