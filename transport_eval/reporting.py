"""Markdown rendering of an :class:`~transport_eval.estimation.Evaluation`.

The rendering keeps the three quantities visibly separate:

1. observed change (before/after in the study corridors),
2. comparison-supported change (difference-in-differences), and
3. unexplained residual.

It ends with a scope statement and an explicit list of what the current input
does *not* support concluding.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .estimation import Evaluation, Limitation
from .workspace import ledger_summary

SEVERITY_LABEL = {"blocking": "阻断", "warning": "警示", "info": "提示"}
GRADE_LABEL = {
    "supported": "对照支持",
    "conditional": "有条件支持",
    "insufficient": "证据不足",
}
DIRECTION_LABEL = {
    "expand_candidate": "可考虑扩大",
    "adjust_or_continue": "建议调整或继续试点",
    "defer_or_adjust": "建议暂缓或调整",
    "defer": "暂缓",
    "review": "需要人工复核",
}
COMPARABILITY_LABEL = {
    "comparable": "可比",
    "conditional": "有条件可比",
    "partially_contaminated": "部分对照已受污染（已移出汇总）",
    "not_comparable": "不可比",
}


def _pct(value: str | None) -> str:
    if value is None or value == "":
        return "—"
    return f"{float(value):+.2%}"


def _num(value: str | None, digits: int = 4) -> str:
    if value is None or value == "":
        return "—"
    return f"{float(value):.{digits}f}"


def _signed(value: str | None, digits: int = 4) -> str:
    if value is None or value == "":
        return "—"
    return f"{float(value):+.{digits}f}"


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _effect_table(evaluation: Evaluation) -> list[str]:
    lines = [
        "| 口径 | 观察变化（处理走廊） | 对照变化 | 对照支持的变化 | 95% 区间 | 无法解释的余量 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for effect in evaluation.effects:
        interval = "—"
        if effect.ci_low is not None and effect.ci_high is not None:
            interval = f"[{float(effect.ci_low):.4f}, {float(effect.ci_high):.4f}]"
        if effect.metric == "counter_relative_change":
            lines.append(
                "| 计数器相对变化 | {obs} | {comp} | {did} | {ci} | {resid} |".format(
                    obs=_pct(_text(effect.treated_change.absolute)),
                    comp=_pct(_text(effect.comparison_change.absolute)),
                    did=_pct(_text(effect.did)),
                    ci=interval,
                    resid=_pct(_text(effect.unexplained)),
                )
            )
            continue
        lines.append(
            "| 每千人使用率 | {obs} | {comp} | {did} | {ci} | {resid} |".format(
                obs=_signed(_text(effect.treated_change.absolute)),
                comp=_signed(_text(effect.comparison_change.absolute)),
                did=_signed(_text(effect.did)),
                ci=interval,
                resid=_signed(_text(effect.unexplained)),
            )
        )
    return lines


def _observation_table(evaluation: Evaluation) -> list[str]:
    lines = [
        "| 走廊 | 观察期 | 服务版本 | 总体量 | 样本量 | 行程数 | 加权行程 | 每千人使用率 | 计数器（原始/校正） |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for observation in evaluation.observations:
        counter = "—"
        if observation.counter_raw is not None:
            adjusted = "—" if observation.counter_adjusted is None else f"{float(observation.counter_adjusted):.1f}"
            counter = f"{observation.counter_raw} / {adjusted}"
        lines.append(
            f"| {observation.corridor_id} | {observation.period_id} | {observation.service_version} | "
            f"{observation.population_n} | {observation.sample_n} | {observation.journeys} | "
            f"{float(observation.weighted_journeys):.1f} | {float(observation.rate_per_1000):.2f} | {counter} |"
        )
    return lines


def _limitation_lines(limitations: Iterable[Limitation]) -> list[str]:
    lines: list[str] = []
    for limitation in limitations:
        scope = f"（范围：{', '.join(limitation.scope)}）" if limitation.scope else ""
        review = " · 需重新审阅" if limitation.review_required else ""
        lines.append(
            f"- **{SEVERITY_LABEL.get(limitation.severity, limitation.severity)} · {limitation.code}**"
            f"{scope}{review}：{limitation.message}"
        )
    return lines


def render_report(
    evaluation: Evaluation,
    *,
    decisions: Sequence[dict[str, object]] = (),
    input_drift: Sequence[str] = (),
) -> str:
    primary = evaluation.effects[0] if evaluation.effects else None
    lines: list[str] = []
    lines.append(f"# 绿色出行措施效果评估 · {evaluation.study_id}")
    lines.append("")
    lines.append(
        f"- 评估基准日：{evaluation.as_of.isoformat()}　"
        f"观察窗口：{evaluation.pre_period} → {evaluation.post_period}"
    )
    lines.append(
        f"- 处理走廊：{evaluation.treated_corridor}　对照走廊："
        f"{', '.join(evaluation.comparison_corridors) if evaluation.comparison_corridors else '无'}"
    )
    lines.append(
        f"- 结论等级：**{GRADE_LABEL.get(evaluation.conclusion_grade, evaluation.conclusion_grade)}**"
    )
    lines.append(
        f"- 结论方向：**{DIRECTION_LABEL.get(str(evaluation.recommendation.get('direction')), evaluation.recommendation.get('direction'))}**"
    )
    if input_drift:
        lines.append(
            "- **证据漂移**：冻结证据对应的输入已改变（" + ", ".join(input_drift) + "），本报告不再对应已批准的决定。"
        )
    lines.append("")

    lines.append("## 1. 措施与观察窗口范围")
    lines.append("")
    lines.append("| 措施 | 名称 | 类型 | 登记适用走廊 | 启用日 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for measure in evaluation.measures:
        lines.append(
            f"| {measure['measure_id']} | {measure['name']} | {measure['kind']} | "
            f"{', '.join(measure['scope_corridors']) or '未登记'} | {measure['activation_date']} |"
        )
    lines.append("")
    lines.append("| 走廊 | 角色 | 观察期 | 措施 | 服务网络版本 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for window in evaluation.windows:
        lines.append(
            f"| {window['corridor_id']} | {window['group_role']} | {window['period_id']} | "
            f"{window['measure_id'] or '—'} | {window['service_version']} |"
        )
    lines.append("")

    lines.append("## 2. 观察到的使用变化")
    lines.append("")
    lines.append("需求单位是**行程**；同一行程的公交、步行等多个路段只计一次。")
    lines.append("")
    lines.extend(_observation_table(evaluation))
    lines.append("")
    if evaluation.observations:
        lines.append("各群体覆盖与使用（前后观察期）：")
        lines.append("")
        lines.append("| 走廊 | 观察期 | 群体 | 样本/总体 | 覆盖率 | 加权行程 | 每千人使用率 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for observation in evaluation.observations:
            for group in observation.groups:
                lines.append(
                    f"| {observation.corridor_id} | {observation.period_id} | {group['group_id']} | "
                    f"{group['sample_n']}/{group['population_n']} | {float(group['coverage']):.2%} | "
                    f"{float(group['weighted_journeys']):.1f} | {float(group['rate_per_1000']):.2f} |"
                )
        lines.append("")
    lines.append("比照基准（未做对照校正）：")
    lines.append("")
    for effect in evaluation.effects:
        if effect.metric != "usage_rate_per_1000":
            continue
        lines.append(
            f"- {evaluation.treated_corridor}：{_num(_text(effect.treated_change.pre_value), 2)} → "
            f"{_num(_text(effect.treated_change.post_value), 2)} 每千人，"
            f"变化 {_signed(_text(effect.treated_change.absolute), 2)}"
            f"（{_pct(_text(effect.treated_change.relative))}）。"
        )
    lines.append("")

    lines.append("## 3. 对照比较支持的变化与仍无法解释的部分")
    lines.append("")
    status_label = COMPARABILITY_LABEL.get(
        str(evaluation.comparability["status"]), str(evaluation.comparability["status"])
    )
    lines.append(f"对照可比性：**{status_label}**")
    retained = evaluation.comparability.get("retained_corridors") or []
    removed = evaluation.comparability.get("removed_corridors") or []
    lines.append(
        f"- 参与汇总的对照：{', '.join(retained) if retained else '无'}"
        + (
            "；已移出："
            + ", ".join(f"{item['corridor_id']}（{', '.join(item['codes'])}）" for item in removed)
            if removed
            else ""
        )
    )
    for reason in evaluation.comparability["reasons"]:
        lines.append(
            f"- [{SEVERITY_LABEL.get(str(reason['severity']), reason['severity'])}] {reason['code']}：{reason['message']}"
        )
    lines.append("")
    lines.extend(_effect_table(evaluation))
    lines.append("")
    if primary is not None:
        lines.append(
            "解读：观察变化 = 对照支持的变化 + 无法解释的余量。"
            "无法解释的部分包含共同的季节波动、对照污染和样本/归属误差，不能被当作措施收益。"
        )
        if primary.ci_low is not None and primary.ci_low <= 0:
            lines.append("对照支持的变化的 95% 区间包含 0，当前证据不足以确认措施带来了净增长。")
        lines.append("")

    if evaluation.sensitivity:
        lines.append("### 敏感性分析")
        lines.append("")
        lines.append("| 口径 | 对照支持的变化 | 95% 区间 | 与主估计差异 | 是否仍支持效果 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for variant in evaluation.sensitivity:
            interval = "—"
            if variant.get("ci_low") and variant.get("ci_high"):
                interval = f"[{float(variant['ci_low']):.4f}, {float(variant['ci_high']):.4f}]"
            supports = variant.get("supports_measure_effect")
            supports_text = "是" if supports is True else ("否" if supports is False else "—")
            lines.append(
                f"| {variant['variant']} | {_num(variant.get('did'))} | {interval} | "
                f"{_num(variant.get('delta_vs_primary'), 4) if variant.get('delta_vs_primary') else '—'} | {supports_text} |"
            )
        lines.append("")

    lines.append("## 4. 样本代表性与覆盖")
    lines.append("")
    representativeness = evaluation.representativeness
    lines.append(
        f"- 最大样本/人口份额偏差：{_pct(representativeness.get('max_share_gap'))}"
        f"　最低覆盖率：{_pct(representativeness.get('min_coverage'))}"
    )
    missing = representativeness.get("groups_missing_periods") or []
    if missing:
        lines.append("- 缺少调查的走廊/观察期：" + ", ".join(str(item) for item in missing))
    lines.append("")
    lines.append("| 走廊 | 观察期 | 群体 | 样本/总体 | 覆盖率 | 人口份额 | 样本份额 | 偏差 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in representativeness.get("rows", []):
        lines.append(
            f"| {row['corridor_id']} | {row['period_id']} | {row['group_id']} | "
            f"{row['sample_n']}/{row['population_n']} | {float(row['coverage']):.2%} | "
            f"{float(row['population_share']):.2%} | {float(row['sample_share']):.2%} | "
            f"{float(row['share_gap']):+.2%} |"
        )
    lines.append("")

    lines.append("## 5. 限制与适用范围")
    lines.append("")
    blocking = [item for item in evaluation.limitations if item.severity == "blocking"]
    warnings = [item for item in evaluation.limitations if item.severity == "warning"]
    info = [item for item in evaluation.limitations if item.severity == "info"]
    if blocking:
        lines.append("**阻断性限制（结论不足以支持扩大投入）**")
        lines.append("")
        lines.extend(_limitation_lines(blocking))
        lines.append("")
    if warnings:
        lines.append("**警示**")
        lines.append("")
        lines.extend(_limitation_lines(warnings))
        lines.append("")
    if info:
        lines.append("**提示**")
        lines.append("")
        lines.extend(_limitation_lines(info))
        lines.append("")
    if not evaluation.limitations:
        lines.append("本次评估未发现限制项。")
        lines.append("")

    lines.append("## 6. 结论方向与理由")
    lines.append("")
    lines.append(
        f"建议方向：**{DIRECTION_LABEL.get(str(evaluation.recommendation.get('direction')), evaluation.recommendation.get('direction'))}**"
    )
    lines.append("")
    for reason in evaluation.recommendation.get("reasons", []):
        lines.append(f"- {reason}")
    lines.append("")

    lines.append("## 7. 数据来源与口径")
    lines.append("")
    provenance = evaluation.provenance
    lines.append(f"- 纳入后续运营资料：{'是' if provenance.get('included_operational') else '否（固定证据口径）'}")
    lines.append(f"- 实际使用的运营行程数：{provenance.get('operational_records_used', 0)}")
    counter = provenance.get("journey_counter", {})
    if counter:
        lines.append(
            "- 行程归属计数："
            f"观察期外 {counter.get('outside_period', 0)}，"
            f"站点不明 {counter.get('unmatched_stop', 0)}，"
            f"走廊外 {counter.get('outside_corridor', 0)}，"
            f"按口径排除的运营行程 {counter.get('operational_excluded', 0)}"
        )
    for note in evaluation.notes:
        lines.append(f"- {note}")
    lines.append("")

    if decisions:
        lines.append("## 8. 已登记的决定")
        lines.append("")
        lines.append("| 决定 | 动作 | 时间 | 证据 | 结论等级 | 被替代 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in ledger_summary(decisions):
            lines.append(
                f"| {row['decision_id']} | {row['action']} | {row['decided_at']} | "
                f"{row['evidence_id']} | {row['conclusion_grade']} | {row['superseded_by'] or '—'} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
