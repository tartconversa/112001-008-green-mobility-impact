"""Command line entry point: ``python -m transport_eval``.

Commands
--------
``evaluate``   load inputs, evaluate a study, print a Markdown report
``freeze``     evaluate and pin the evidence snapshot a decision will cite
``decide``     register an expand / adjust / defer / continue decision
``ledger``     list registered decisions
``verify``     check whether the inputs still match a frozen snapshot
``compare``    diff current evidence against a frozen snapshot

All commands print JSON on ``--json``; otherwise ``evaluate`` prints Markdown.
Exit codes: 0 success, 1 validation/input error, 2 integrity violation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import EvaluationError, InputError, IntegrityError, ValidationError
from .estimation import evaluate
from .loading import load_workspace
from .reporting import render_report
from .workspace import StudyWorkspace, ledger_summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m transport_eval",
        description="绿色出行措施效果评估工具",
    )
    parser.add_argument("--data", default="examples/pilot", help="输入数据目录")
    parser.add_argument("--workspace", default=None, help="证据与决定目录（默认 <data>/workspace）")
    sub = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = sub.add_parser("evaluate", help="评估研究并输出报告")
    evaluate_parser.add_argument("--study", default=None)
    evaluate_parser.add_argument("--as-of", default=None)
    evaluate_parser.add_argument(
        "--exclude-operational",
        action="store_true",
        help="按当时冻结的证据口径评估，排除后续运营资料",
    )
    evaluate_parser.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    evaluate_parser.add_argument("--out", default=None, help="把报告写入文件")
    evaluate_parser.add_argument("--decisions", action="store_true", help="报告末尾附上已登记决定")

    freeze_parser = sub.add_parser("freeze", help="冻结一份证据快照")
    freeze_parser.add_argument("--study", default=None)
    freeze_parser.add_argument("--as-of", default=None)
    freeze_parser.add_argument("--exclude-operational", action="store_true")

    decide_parser = sub.add_parser("decide", help="针对冻结证据登记决定")
    decide_parser.add_argument("--evidence", required=True)
    decide_parser.add_argument(
        "--action", required=True, choices=("expand", "adjust", "defer", "continue")
    )
    decide_parser.add_argument("--rationale", required=True)
    decide_parser.add_argument(
        "--acknowledge",
        action="append",
        default=[],
        help="确认的需复核限制代码，可重复",
    )
    decide_parser.add_argument("--supersedes", default=None)
    decide_parser.add_argument("--by", default="")

    verify_parser = sub.add_parser("verify", help="校验冻结证据是否仍与输入一致")
    verify_parser.add_argument("--evidence", required=True)

    compare_parser = sub.add_parser("compare", help="对比当前证据与冻结快照")
    compare_parser.add_argument("--evidence", required=True)
    compare_parser.add_argument("--as-of", default=None)
    compare_parser.add_argument("--exclude-operational", action="store_true")

    sub.add_parser("ledger", help="列出已登记决定")
    return parser


def _workspace(args: argparse.Namespace) -> StudyWorkspace:
    return StudyWorkspace(args.data, args.workspace)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    workspace = _workspace(args)
    try:
        if args.command == "ledger":
            _print_json(ledger_summary(workspace.decisions()))
            return 0

        if args.command == "verify":
            drifted = workspace.verify_snapshot(args.evidence)
            added = workspace.new_inputs(args.evidence)
            payload = {
                "evidence_id": args.evidence,
                "input_drift": list(drifted),
                "new_inputs_since_freeze": list(added),
                "ok": not drifted,
            }
            _print_json(payload)
            return 0 if not drifted else 2

        if args.command == "freeze":
            snapshot = workspace.freeze(
                args.study or _only_study(workspace),
                as_of=args.as_of,
                include_operational=not args.exclude_operational,
            )
            _print_json(
                {
                    "evidence_id": snapshot.evidence_id,
                    "study_id": snapshot.study_id,
                    "as_of": snapshot.as_of,
                    "include_operational": snapshot.include_operational,
                    "conclusion_grade": snapshot.evaluation.get("conclusion_grade"),
                    "review_codes": snapshot.evaluation.get("review_codes"),
                    "digests": snapshot.digests,
                }
            )
            return 0

        if args.command == "decide":
            entry = workspace.record_decision(
                args.evidence,
                action=args.action,
                rationale=args.rationale,
                acknowledged_limitations=args.acknowledge,
                supersedes=args.supersedes,
                decided_by=args.by,
            )
            _print_json(entry)
            return 0

        if args.command == "compare":
            payload = workspace.compare_with_snapshot(
                args.evidence,
                as_of=args.as_of,
                include_operational=not args.exclude_operational,
            )
            _print_json(payload)
            return 0

        if args.command == "evaluate":
            inputs = workspace.load()
            evaluation = evaluate(
                inputs,
                args.study,
                as_of=args.as_of,
                include_operational=not args.exclude_operational,
            )
            if args.json:
                _print_json(evaluation.as_dict())
                return 0
            decisions = workspace.decisions() if args.decisions else []
            text = render_report(evaluation, decisions=decisions)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print(f"报告已写入 {args.out}")
            else:
                print(text, end="")
            return 0

        parser.error(f"未知命令 {args.command}")
        return 1
    except IntegrityError as exc:
        print(f"完整性错误: {exc}", file=sys.stderr)
        return 2
    except (ValidationError, InputError) as exc:
        print(f"输入错误: {exc}", file=sys.stderr)
        return 1
    except EvaluationError as exc:
        print(f"评估错误: {exc}", file=sys.stderr)
        return 1


def _only_study(workspace: StudyWorkspace) -> str:
    study_ids = load_workspace(workspace.data_dir).study_ids()
    if len(study_ids) != 1:
        raise ValidationError(f"研究数量为 {len(study_ids)}，请用 --study 指定研究")
    return study_ids[0]


if __name__ == "__main__":
    raise SystemExit(main())
