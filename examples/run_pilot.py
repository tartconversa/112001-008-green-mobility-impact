#!/usr/bin/env python3
"""Walk the pilot through the full evaluation -> decision -> new-evidence chain.

Run from the repository root::

    python examples/run_pilot.py

The script copies the example into a temporary directory, so the checked-in
fixtures are never modified.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from transport_eval import evaluate, render_report  # noqa: E402
from transport_eval.loading import load_workspace  # noqa: E402
from transport_eval.workspace import StudyWorkspace  # noqa: E402

PILOT = ROOT / "examples" / "pilot"


def heading(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        data = Path(temp) / "pilot"
        shutil.copytree(PILOT, data)
        workspace = StudyWorkspace(data)

        heading("1. 冻结决定所依据的证据")
        snapshot = workspace.freeze("PILOT", include_operational=False)
        print(f"证据编号：{snapshot.evidence_id}")
        print(f"结论等级：{snapshot.evaluation['conclusion_grade']}")
        print("需复核事项：")
        for code in snapshot.evaluation["review_codes"]:
            print(f"  - {code}")

        heading("2. 登记决定（交通部门）")
        decision = workspace.record_decision(
            snapshot.evidence_id,
            action="adjust",
            rationale="对照支持的变化为正，但对照走廊受污染且站点搬迁，需先在小范围调整班次并保留证据。",
            acknowledged_limitations=snapshot.evaluation["review_codes"],
            decided_by="transport-office",
        )
        print(f"决定编号：{decision['decision_id']}")
        print(f"动作：{decision['action']}")
        print(f"引用证据：{decision['evidence_id']}")

        heading("3. 扩围后新增运营资料")
        operational = data / "operational"
        operational.mkdir(exist_ok=True)
        with (operational / "trip_legs.csv").open("w", encoding="utf-8") as stream:
            stream.write(
                "journey_id,leg_no,mode,from_stop,to_stop,depart_at,person_group,sample_weight\n"
            )
            for i in range(1, 6):
                stream.write(f"OP{i:03d},1,bus,A,B,2026-06-{i:02d}T08:00,commuters,1.0\n")
        print(f"新增运营文件：{workspace.new_inputs(snapshot.evidence_id)}")

        heading("4. 校验冻结证据未被改写")
        drift = workspace.verify_snapshot(snapshot.evidence_id)
        print(f"输入漂移：{list(drift) or '无'}")

        heading("5. 新证据进入后续评估")
        later = workspace.evaluate("PILOT", include_operational=True, as_of=date(2026, 7, 31))
        comparison = workspace.compare_with_snapshot(snapshot.evidence_id)
        print(f"随后评估使用的运营行程：{later.provenance['operational_records_used']}")
        print(f"主估计（当时）：{comparison['primary_effect_prior']}")
        print(f"主估计（现在）：{comparison['primary_effect_current']}")
        print(f"新增限制：{comparison['new_limitations'] or '无'}")

        heading("6. 已登记决定")
        for entry in workspace.decisions():
            print(
                f"{entry['decision_id']}  {entry['action']}  {entry['decided_at']}  "
                f"证据 {entry['evidence_id']}  触发 {[item['code'] for item in entry['review_triggers']]}"
            )

        heading("7. 报告片段")
        report = render_report(later, decisions=workspace.decisions())
        print("\n".join(report.splitlines()[:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
