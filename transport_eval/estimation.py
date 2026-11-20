"""Estimation of observed, comparison-supported, and unexplained change.

Design choices worth stating plainly:

* The unit of demand is a **journey**, never a leg.  A journey with a bus leg
  and a metro leg contributes one observation with one expansion weight.
* Before/after comparisons run on a per-1,000-resident usage rate.  The
  denominator comes from the survey ``population_n`` for the same corridor and
  period; that is an assumption, so it is recorded as a limitation and tested
  in the sensitivity section.
* The control-corridor change is subtracted from the treated-corridor change to
  obtain the comparison-supported estimate.  Whatever remains of the observed
  change is reported separately as unexplained: it includes shared seasonal
  movement, comparison contamination, and sample/assignment error.
* Every comparability or provenance problem that could change the conclusion is
  a limitation with a stable code, so later reviews can say exactly which input
  change triggered them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from .errors import ValidationError
from .model import (
    NetworkChange,
    NetworkSegment,
    Period,
    StudyInputs,
    StudyWindow,
    SurveyAmendment,
)

ZERO = Decimal("0")
ONE = Decimal("1")
THOUSAND = Decimal("1000")


@dataclass(frozen=True)
class Limitation:
    code: str
    severity: str  # "blocking" | "warning" | "info"
    message: str
    scope: tuple[str, ...] = ()
    review_required: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "scope": list(self.scope),
            "review_required": self.review_required,
        }


@dataclass(frozen=True)
class EffectiveSurvey:
    record_id: str
    corridor_id: str
    period_id: str
    group_id: str
    sample_n: int
    population_n: int
    base_sample_n: int
    base_population_n: int
    amendment_ids: tuple[str, ...]
    source: str

    @property
    def amended(self) -> bool:
        return bool(self.amendment_ids)

    @property
    def coverage(self) -> Decimal:
        return Decimal(self.sample_n) / Decimal(self.population_n)


@dataclass(frozen=True)
class JourneyAssignment:
    journey_id: str
    corridor_id: str
    period_id: str
    group_id: str
    weight: Decimal
    weight_squared: Decimal
    depart_day: date
    source: str
    off_version: bool
    relocated: bool


@dataclass(frozen=True)
class CorridorPeriodStats:
    corridor_id: str
    period_id: str
    service_version: str
    population_n: int
    sample_n: int
    journeys: int
    weighted_journeys: Decimal
    weight_squared: Decimal
    rate_per_1000: Decimal
    rate_se: Decimal
    off_version_journeys: int
    relocated_journeys: int
    groups: tuple[dict[str, object], ...]
    counter_raw: int | None
    counter_adjusted: Decimal | None
    counter_stops: tuple[str, ...]
    counter_coverage_min: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "corridor_id": self.corridor_id,
            "period_id": self.period_id,
            "service_version": self.service_version,
            "population_n": self.population_n,
            "sample_n": self.sample_n,
            "journeys": self.journeys,
            "weighted_journeys": f"{self.weighted_journeys:.4f}",
            "rate_per_1000": f"{self.rate_per_1000:.4f}",
            "rate_se": f"{self.rate_se:.4f}",
            "off_version_journeys": self.off_version_journeys,
            "relocated_journeys": self.relocated_journeys,
            "groups": list(self.groups),
            "counter_raw": self.counter_raw,
            "counter_adjusted": None if self.counter_adjusted is None else f"{self.counter_adjusted:.4f}",
            "counter_stops": list(self.counter_stops),
            "counter_coverage_min": None if self.counter_coverage_min is None else f"{self.counter_coverage_min:.4f}",
        }


@dataclass(frozen=True)
class Change:
    metric: str
    corridor_id: str
    pre_period: str
    post_period: str
    pre_value: Decimal | None
    post_value: Decimal | None
    absolute: Decimal | None
    relative: Decimal | None
    se: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "corridor_id": self.corridor_id,
            "pre_period": self.pre_period,
            "post_period": self.post_period,
            "pre_value": None if self.pre_value is None else f"{self.pre_value:.4f}",
            "post_value": None if self.post_value is None else f"{self.post_value:.4f}",
            "absolute": None if self.absolute is None else f"{self.absolute:.4f}",
            "relative": None if self.relative is None else f"{self.relative:.4f}",
            "se": None if self.se is None else f"{self.se:.4f}",
        }


@dataclass(frozen=True)
class Effect:
    metric: str
    treated_change: Change
    comparison_change: Change
    did: Decimal | None
    did_se: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    unexplained: Decimal | None
    supports_measure_effect: bool
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "treated_change": self.treated_change.as_dict(),
            "comparison_change": self.comparison_change.as_dict(),
            "did": None if self.did is None else f"{self.did:.4f}",
            "did_se": None if self.did_se is None else f"{self.did_se:.4f}",
            "ci_low": None if self.ci_low is None else f"{self.ci_low:.4f}",
            "ci_high": None if self.ci_high is None else f"{self.ci_high:.4f}",
            "unexplained": None if self.unexplained is None else f"{self.unexplained:.4f}",
            "supports_measure_effect": self.supports_measure_effect,
            "note": self.note,
        }


@dataclass
class Evaluation:
    study_id: str
    as_of: date
    include_operational: bool
    pre_period: str
    post_period: str
    treated_corridor: str
    comparison_corridors: tuple[str, ...]
    measures: tuple[dict[str, object], ...]
    windows: tuple[dict[str, object], ...]
    observations: tuple[CorridorPeriodStats, ...]
    representativeness: dict[str, object]
    comparability: dict[str, object]
    effects: tuple[Effect, ...]
    sensitivity: tuple[dict[str, object], ...]
    limitations: tuple[Limitation, ...]
    recommendation: dict[str, object]
    provenance: dict[str, object]
    existing_decisions: tuple[dict[str, object], ...]
    notes: tuple[str, ...]

    @property
    def limitation_codes(self) -> tuple[str, ...]:
        return tuple(limitation.code for limitation in self.limitations)

    @property
    def review_codes(self) -> tuple[str, ...]:
        return tuple(
            limitation.code for limitation in self.limitations if limitation.review_required
        )

    @property
    def blocking_codes(self) -> tuple[str, ...]:
        return tuple(
            limitation.code for limitation in self.limitations if limitation.severity == "blocking"
        )

    @property
    def conclusion_grade(self) -> str:
        if self.blocking_codes:
            return "insufficient"
        if any(limitation.severity == "warning" for limitation in self.limitations):
            return "conditional"
        return "supported"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "transport-eval/evaluation-v1",
            "study_id": self.study_id,
            "as_of": self.as_of.isoformat(),
            "include_operational": self.include_operational,
            "pre_period": self.pre_period,
            "post_period": self.post_period,
            "treated_corridor": self.treated_corridor,
            "comparison_corridors": list(self.comparison_corridors),
            "measures": list(self.measures),
            "windows": list(self.windows),
            "observations": [observation.as_dict() for observation in self.observations],
            "representativeness": self.representativeness,
            "comparability": self.comparability,
            "effects": [effect.as_dict() for effect in self.effects],
            "sensitivity": list(self.sensitivity),
            "limitations": [limitation.as_dict() for limitation in self.limitations],
            "limitation_codes": list(self.limitation_codes),
            "blocking_codes": list(self.blocking_codes),
            "review_codes": list(self.review_codes),
            "conclusion_grade": self.conclusion_grade,
            "recommendation": self.recommendation,
            "provenance": self.provenance,
            "existing_decisions": list(self.existing_decisions),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Effective survey state
# ---------------------------------------------------------------------------


def _latest_amendments(
    amendments: Sequence[SurveyAmendment], as_of: date
) -> dict[str, SurveyAmendment]:
    latest: dict[str, SurveyAmendment] = {}
    for amendment in sorted(amendments, key=lambda item: (item.effective_date, item.amendment_id)):
        if amendment.effective_date > as_of:
            continue
        current = latest.get(amendment.record_id)
        if current is None or amendment.effective_date >= current.effective_date:
            latest[amendment.record_id] = amendment
    return latest


def effective_surveys(
    inputs: StudyInputs, as_of: date
) -> tuple[dict[tuple[str, str, str, str], EffectiveSurvey], tuple[Limitation, ...]]:
    """Apply survey supplements and group migrations effective on ``as_of``.

    A supplement replaces the recorded sample and population totals.  A group
    migration moves ``moved_count`` respondents from the source group to the
    target group; the source reminder is deducted and the target is topped up,
    so the corridor/period total is preserved unless a supplement explicitly
    changed it.
    """

    latest = _latest_amendments(inputs.amendments, as_of)
    limitations: list[Limitation] = []

    # (study, corridor, period, group) -> [sample_delta, population_delta]
    deltas: dict[tuple[str, str, str, str], list[int]] = {}
    touch_ids: dict[tuple[str, str, str, str], set[str]] = {}

    def _touch(key: tuple[str, str, str, str], amendment_id: str) -> None:
        deltas.setdefault(key, [0, 0])
        touch_ids.setdefault(key, set()).add(amendment_id)

    for record in inputs.surveys:
        amendment = latest.get(record.record_id)
        if amendment is None:
            continue
        key = (record.study_id, record.corridor_id, record.period_id, record.group_id)
        _touch(key, amendment.amendment_id)
        deltas[key][0] += amendment.new_sample_n - record.sample_n
        deltas[key][1] += amendment.new_population_n - record.population_n
        if amendment.moved_count <= 0 or not amendment.moved_to_group:
            continue
        if amendment.moved_from_group and amendment.moved_from_group != record.group_id:
            raise ValidationError(
                f"修订 {amendment.amendment_id}: 迁移来源群体 {amendment.moved_from_group} "
                f"与调查记录群体 {record.group_id} 不一致"
            )
        source_key = key
        target_key = (record.study_id, record.corridor_id, record.period_id, amendment.moved_to_group)
        deltas[source_key][0] -= amendment.moved_count
        deltas[source_key][1] -= amendment.moved_count
        _touch(target_key, amendment.amendment_id)
        deltas[target_key][0] += amendment.moved_count
        deltas[target_key][1] += amendment.moved_count
        if target_key not in {
            (item.study_id, item.corridor_id, item.period_id, item.group_id) for item in inputs.surveys
        }:
            limitations.append(
                Limitation(
                    "SURVEY_MIGRATION_TARGET_MISSING",
                    "warning",
                    f"修订 {amendment.amendment_id} 将 {amendment.moved_count} 人迁入"
                    f" {amendment.moved_to_group}，但该群体在同期没有调查记录；群体估计范围可能不完整。",
                    (record.corridor_id, record.period_id),
                    True,
                )
            )

    effective: dict[tuple[str, str, str, str], EffectiveSurvey] = {}
    for record in inputs.surveys:
        key = (record.study_id, record.corridor_id, record.period_id, record.group_id)
        sample_delta, population_delta = deltas.get(key, [0, 0])
        effective[key] = EffectiveSurvey(
            record.record_id,
            record.corridor_id,
            record.period_id,
            record.group_id,
            record.sample_n + sample_delta,
            record.population_n + population_delta,
            record.sample_n,
            record.population_n,
            tuple(sorted(touch_ids.get(key, ()))),
            record.source,
        )

    for key, survey in effective.items():
        if survey.sample_n < 0 or survey.population_n <= 0:
            raise ValidationError(
                f"调查修订后 {key[1]} / {key[2]} / {key[3]} 的样本或总体量无效"
            )
        if survey.sample_n > survey.population_n:
            limitations.append(
                Limitation(
                    "SURVEY_AMENDMENT_SAMPLE_EXCEEDS_POPULATION",
                    "warning",
                    f"{key[1]} {key[2]} {key[3]} 修订后样本量大于总体量，群体份额估计不可靠。",
                    (key[1], key[2]),
                    True,
                )
            )

    for amendment in inputs.amendments:
        if amendment.effective_date > as_of:
            continue
        record = next((item for item in inputs.surveys if item.record_id == amendment.record_id), None)
        if record is None:
            continue
        period = inputs.periods[record.period_id]
        if period.start <= amendment.effective_date <= period.end:
            limitations.append(
                Limitation(
                    "SURVEY_AMENDMENT_IN_WINDOW",
                    "blocking",
                    f"调查修订 {amendment.amendment_id} 在观察期 {period.period_id} 内生效，"
                    "人群归属与估计范围在窗口中途改变，前后比较不再同口径。",
                    (record.corridor_id, period.period_id),
                    True,
                )
            )
        else:
            limitations.append(
                Limitation(
                    "SURVEY_AMENDMENT_POST_HOC",
                    "warning",
                    f"调查修订 {amendment.amendment_id} 在观察期之后生效"
                    f"（{amendment.effective_date.isoformat()}），已被纳入当前估计；"
                    "此前冻结的证据不包含该修订，需重新审阅。",
                    (record.corridor_id, period.period_id),
                    True,
                )
            )
    return effective, tuple(limitations)


# ---------------------------------------------------------------------------
# Network attribution
# ---------------------------------------------------------------------------


def _segment_area(
    segments: Sequence[NetworkSegment],
    changes: Sequence[NetworkChange],
    stop_id: str,
    day: date,
) -> tuple[str | None, bool, bool]:
    """Return (area, ambiguous, relocated) for a stop on a given day."""

    applicable = [
        change
        for change in changes
        if change.stop_id == stop_id and change.effective_date <= day
    ]
    relocated = bool(applicable)
    if applicable:
        latest = max(applicable, key=lambda item: (item.effective_date, item.change_id))
        return latest.to_area or None, False, relocated
    candidates = [
        segment for segment in segments if segment.stop_id == stop_id and segment.valid_on(day)
    ]
    areas = {segment.area_id for segment in candidates}
    if not areas:
        return None, False, relocated
    if len(areas) > 1:
        return None, True, relocated
    return next(iter(areas)), False, relocated


def _corridor_for_area(inputs: StudyInputs, area: str | None) -> str | None:
    if area is None:
        return None
    matches = [corridor.corridor_id for corridor in inputs.corridors.values() if corridor.area_id == area]
    return matches[0] if len(matches) == 1 else None


def _has_version(
    segments: Sequence[NetworkSegment], stop_id: str, version: str, day: date
) -> bool:
    return any(
        segment.stop_id == stop_id
        and segment.version == version
        and segment.valid_on(day)
        for segment in segments
    )


def _periods_for_study(inputs: StudyInputs, study_id: str) -> list[Period]:
    period_ids = {window.period_id for window in inputs.study_windows if window.study_id == study_id}
    return sorted((inputs.periods[period_id] for period_id in period_ids), key=lambda item: item.start)


def _period_id_on(periods: Sequence[Period], day: date) -> str | None:
    for period in periods:
        if period.start <= day <= period.end:
            return period.period_id
    return None


def _assign_journeys(
    inputs: StudyInputs,
    study_id: str,
    as_of: date,
    include_operational: bool,
    *,
    pin_stop_areas_to: date | None = None,
) -> tuple[list[JourneyAssignment], list[Limitation], dict[str, int]]:
    """Assign each journey to one corridor and one observation period.

    ``pin_stop_areas_to`` keeps stops at the area they had on that date, which
    is used by the sensitivity analysis for stop relocations.
    """
    windows = {
        (window.corridor_id, window.period_id): window
        for window in inputs.study_windows
        if window.study_id == study_id
    }
    periods = _periods_for_study(inputs, study_id)
    study_corridors = {corridor_id for corridor_id, _period in windows}
    assignments: list[JourneyAssignment] = []
    limitations: list[Limitation] = []
    counters = {
        "outside_period": 0,
        "unmatched_stop": 0,
        "outside_corridor": 0,
        "operational_excluded": 0,
        "relocated_outside_corridor": 0,
    }
    unmatched_stops: set[str] = set()
    ambiguous_stops: set[str] = set()

    for journey in inputs.journeys.values():
        source = journey.legs[0].source
        if source.startswith("operational/") and not include_operational:
            counters["operational_excluded"] += 1
            continue
        day = journey.depart_at.date()
        period_id = _period_id_on(periods, day)
        if period_id is None:
            counters["outside_period"] += 1
            continue
        origin = journey.legs[0].from_stop
        design_day = min(day, pin_stop_areas_to) if pin_stop_areas_to is not None else day
        area, ambiguous, relocated = _segment_area(inputs.network, inputs.network_changes, origin, design_day)
        if ambiguous:
            ambiguous_stops.add(origin)
            counters["unmatched_stop"] += 1
            continue
        corridor_id = _corridor_for_area(inputs, area)
        if corridor_id is None or corridor_id not in study_corridors:
            counters["outside_corridor"] += 1
            if relocated:
                counters["relocated_outside_corridor"] += 1
            continue
        window = windows[(corridor_id, period_id)]
        off_version = not _has_version(inputs.network, origin, window.service_version, day)
        assignments.append(
            JourneyAssignment(
                journey.journey_id,
                corridor_id,
                period_id,
                journey.person_group,
                journey.sample_weight,
                journey.sample_weight * journey.sample_weight,
                day,
                source,
                off_version,
                relocated,
            )
        )

    if unmatched_stops:
        limitations.append(
            Limitation(
                "AMBIGUOUS_STOP_ASSIGNMENT",
                "warning",
                f"站点 {', '.join(sorted(unmatched_stops))} 存在多个同时有效的区域版本，"
                "无法唯一归属走廊，相关行程已排除。",
                tuple(sorted(unmatched_stops)),
            )
        )
    if counters["outside_period"]:
        limitations.append(
            Limitation(
                "JOURNEYS_OUTSIDE_PERIOD",
                "info",
                f"{counters['outside_period']} 条行程的出发时间不在研究观察期内，未纳入估计。",
            )
        )
    if counters["outside_corridor"]:
        limitations.append(
            Limitation(
                "JOURNEYS_OUTSIDE_CORRIDOR",
                "info",
                f"{counters['outside_corridor']} 条行程的出发站点不属于任何研究走廊，未纳入估计。",
            )
        )
    if counters["operational_excluded"]:
        limitations.append(
            Limitation(
                "OPERATIONAL_DATA_EXCLUDED",
                "info",
                f"按固定证据口径评估，已排除 {counters['operational_excluded']} 条后续运营行程。",
            )
        )
    return assignments, limitations, counters


# ---------------------------------------------------------------------------
# Corridor-period aggregation
# ---------------------------------------------------------------------------


def _corridor_period_stats(
    inputs: StudyInputs,
    study_id: str,
    period_id: str,
    corridor_id: str,
    window: StudyWindow,
    surveys: Mapping[tuple[str, str, str, str], EffectiveSurvey],
    assignments: Sequence[JourneyAssignment],
    *,
    exclude_off_version: bool = False,
    exclude_relocated: bool = False,
    base_denominator: bool = False,
) -> CorridorPeriodStats:
    period_surveys = [
        survey
        for (candidate_study, candidate_corridor, candidate_period, _group), survey in surveys.items()
        if candidate_study == study_id and candidate_corridor == corridor_id and candidate_period == period_id
    ]
    population = sum(
        (survey.base_population_n if base_denominator else survey.population_n) for survey in period_surveys
    )
    sample = sum(survey.base_sample_n if base_denominator else survey.sample_n for survey in period_surveys)

    relevant = [assignment for assignment in assignments if assignment.corridor_id == corridor_id and assignment.period_id == period_id]
    off_version = [item for item in relevant if item.off_version]
    relocated = [item for item in relevant if item.relocated]
    if exclude_off_version:
        relevant = [item for item in relevant if not item.off_version]
    if exclude_relocated:
        relevant = [item for item in relevant if not item.relocated]

    weighted = sum((item.weight for item in relevant), ZERO)
    weight_sq = sum((item.weight_squared for item in relevant), ZERO)
    rate = (weighted / Decimal(population) * THOUSAND) if population else ZERO
    se = (weight_sq.sqrt() / Decimal(population) * THOUSAND) if population else ZERO

    group_rows: list[dict[str, object]] = []
    for survey in sorted(period_surveys, key=lambda item: item.group_id):
        members = [item for item in relevant if item.group_id == survey.group_id]
        group_weight = sum((item.weight for item in members), ZERO)
        denom = survey.base_population_n if base_denominator else survey.population_n
        group_rate = group_weight / Decimal(denom) * THOUSAND if denom else ZERO
        group_rows.append(
            {
                "group_id": survey.group_id,
                "sample_n": survey.base_sample_n if base_denominator else survey.sample_n,
                "population_n": denom,
                "coverage": f"{(Decimal(survey.base_sample_n if base_denominator else survey.sample_n) / Decimal(denom)):.4f}",
                "journeys": len(members),
                "weighted_journeys": f"{group_weight:.4f}",
                "rate_per_1000": f"{group_rate:.4f}",
                "amendment_ids": list(survey.amendment_ids),
            }
        )

    counters = [
        counter
        for counter in inputs.counters
        if counter.study_id == study_id
        and counter.corridor_id == corridor_id
        and counter.period_id == period_id
    ]
    counter_raw = sum(counter.observed_count for counter in counters) if counters else None
    counter_adjusted = (
        sum((Decimal(counter.observed_count) / counter.coverage_ratio for counter in counters), ZERO)
        if counters
        else None
    )
    coverage_values = [counter.coverage_ratio for counter in counters]
    coverage_min = min(coverage_values) if coverage_values else None

    return CorridorPeriodStats(
        corridor_id,
        period_id,
        window.service_version,
        population,
        sample,
        len(relevant),
        weighted,
        weight_sq,
        rate,
        se,
        len(off_version),
        len(relocated),
        tuple(group_rows),
        counter_raw,
        counter_adjusted,
        tuple(sorted({counter.stop_id for counter in counters})),
        coverage_min,
    )


def _change(metric: str, pre: CorridorPeriodStats, post: CorridorPeriodStats, pre_value: Decimal, post_value: Decimal) -> Change:
    absolute = post_value - pre_value
    relative = absolute / pre_value if pre_value != 0 else None
    se = (pre.rate_se * pre.rate_se + post.rate_se * post.rate_se).sqrt()
    return Change(metric, pre.corridor_id, pre.period_id, post.period_id, pre_value, post_value, absolute, relative, se)


def _pooled_comparison_change(
    metric: str,
    pairs: Sequence[tuple[Change, CorridorPeriodStats]],
) -> Change:
    """Population-weighted average of comparison-corridor changes."""

    usable = [(change, pre) for change, pre in pairs if change.absolute is not None]
    if not usable:
        first = pairs[0][0]
        return Change(metric, "comparison", first.pre_period, first.post_period, None, None, None, None, None)
    weights = [Decimal(max(pre.population_n, 1)) for _change, pre in usable]
    total_weight = sum(weights, ZERO)
    absolute = sum((change.absolute * weight for (change, _pre), weight in zip(usable, weights)), ZERO) / total_weight
    relative = (
        sum(
            (change.relative * weight for (change, _pre), weight in zip(usable, weights) if change.relative is not None),
            ZERO,
        )
        / total_weight
        if all(change.relative is not None for change, _pre in usable)
        else None
    )
    se_sq = sum(
        ((change.se * weight) ** 2 for (change, _pre), weight in zip(usable, weights) if change.se is not None),
        ZERO,
    )
    se = (se_sq.sqrt() / total_weight) if se_sq else None
    return Change(
        metric,
        "comparison",
        usable[0][0].pre_period,
        usable[0][0].post_period,
        None,
        None,
        absolute,
        relative,
        se,
    )


def _effect(
    metric: str,
    treated: Change,
    comparison: Change,
    note: str,
) -> Effect:
    if treated.absolute is None or comparison.absolute is None:
        return Effect(metric, treated, comparison, None, None, None, None, None, False, note)
    did = treated.absolute - comparison.absolute
    se = None
    if treated.se is not None and comparison.se is not None:
        se = (treated.se * treated.se + comparison.se * comparison.se).sqrt()
    ci_low = did - Decimal("1.96") * se if se is not None else None
    ci_high = did + Decimal("1.96") * se if se is not None else None
    supports = bool(ci_low is not None and ci_low > 0)
    unexplained = treated.absolute - did
    return Effect(
        metric,
        treated,
        comparison,
        did,
        se,
        ci_low,
        ci_high,
        unexplained,
        supports,
        note,
    )


# ---------------------------------------------------------------------------
# Comparability, representativeness, limitations
# ---------------------------------------------------------------------------


def _comparability(
    inputs: StudyInputs,
    study_id: str,
    treated_corridor: str,
    comparison_corridors: Sequence[str],
    pre_period: Period,
    post_period: Period,
    stats: Mapping[tuple[str, str], CorridorPeriodStats],
    measures: Sequence[Mapping[str, object]],
    warnings: list[Limitation],
) -> dict[str, object]:
    """Check each comparison corridor and drop the ones that are contaminated.

    A corridor that received a similar measure, changed its service version, or
    had a stop relocated during the window is removed from the comparison set
    with a blocking reason.  It is still reported, so the department can see
    why it is no longer a valid reference; the remaining corridors are pooled.
    """

    reasons: list[dict[str, object]] = []
    retained: list[str] = []
    removed: list[dict[str, object]] = []

    for corridor_id in comparison_corridors:
        corridor_reasons: list[dict[str, object]] = []
        windows = [
            window
            for window in inputs.study_windows
            if window.study_id == study_id and window.corridor_id == corridor_id
        ]
        if any(window.measure_ids for window in windows):
            corridor_reasons.append(
                {
                    "code": "COMPARISON_WINDOW_HAS_MEASURE",
                    "severity": "blocking",
                    "message": f"对照走廊 {corridor_id} 在观察窗口内登记了措施，不能继续作为未受影响的参照。",
                }
            )
        for measure in measures:
            if corridor_id in measure["scope_corridors"]:
                activation = date.fromisoformat(str(measure["activation_date"]))
                if activation <= post_period.end:
                    corridor_reasons.append(
                        {
                            "code": "COMPARISON_IN_MEASURE_SCOPE",
                            "severity": "blocking",
                            "message": f"措施 {measure['measure_id']} 的登记范围包含对照走廊 {corridor_id}，"
                            f"且启用日 {activation.isoformat()} 不晚于后观察期结束。",
                        }
                    )
        comparison_version = {
            window.period_id: window.service_version
            for window in windows
            if window.period_id in {pre_period.period_id, post_period.period_id}
        }
        if len(set(comparison_version.values())) > 1:
            corridor_reasons.append(
                {
                    "code": "COMPARISON_SERVICE_VERSION_CHANGED",
                    "severity": "blocking",
                    "message": f"对照走廊 {corridor_id} 的服务网络版本在前后观察期之间发生变化"
                    f"（{comparison_version.get(pre_period.period_id)} → {comparison_version.get(post_period.period_id)}），"
                    "对照期内也发生了服务调整。",
                }
            )
        corridor_stops = _corridor_stops(inputs, corridor_id, pre_period.start)
        for change in inputs.network_changes:
            if change.stop_id in corridor_stops and pre_period.start <= change.effective_date <= post_period.end:
                corridor_reasons.append(
                    {
                        "code": "COMPARISON_STOP_RELOCATED",
                        "severity": "blocking",
                        "message": f"对照走廊 {corridor_id} 的站点 {change.stop_id} 在观察期内发生变更"
                        f"（{change.effective_date.isoformat()}），人群归属可能改变。",
                    }
                )
        pre_stats = stats.get((corridor_id, pre_period.period_id))
        post_stats = stats.get((corridor_id, post_period.period_id))
        if pre_stats and post_stats:
            if pre_stats.population_n and post_stats.population_n:
                population_change = abs(Decimal(post_stats.population_n - pre_stats.population_n)) / Decimal(
                    pre_stats.population_n
                )
                if population_change > Decimal("0.10"):
                    corridor_reasons.append(
                        {
                            "code": "COMPARISON_POPULATION_SHIFT",
                            "severity": "warning",
                            "message": f"对照走廊 {corridor_id} 的总体人口在前后观察期变化 {population_change:.1%}，"
                            "对照区域的可比性下降。",
                        }
                    )
            coverage_delta = _coverage_shift(pre_stats, post_stats)
            if coverage_delta is not None and coverage_delta > Decimal("0.05"):
                corridor_reasons.append(
                    {
                        "code": "COUNTER_COVERAGE_SHIFT",
                        "severity": "warning",
                        "message": f"对照走廊 {corridor_id} 的计数器覆盖率在前后观察期变化 {coverage_delta:.2f}，"
                        "原始计数的变化可能来自观测覆盖而非客流。",
                    }
                )

        blocking_here = [item for item in corridor_reasons if item["severity"] == "blocking"]
        for reason in corridor_reasons:
            reason["corridor_id"] = corridor_id
            reasons.append(reason)
            if reason["severity"] == "warning":
                warnings.append(
                    Limitation(
                        str(reason["code"]),
                        "warning",
                        str(reason["message"]),
                        (corridor_id,),
                    )
                )
        if blocking_here:
            removed.append(
                {
                    "corridor_id": corridor_id,
                    "codes": sorted({str(item["code"]) for item in blocking_here}),
                }
            )
        else:
            retained.append(corridor_id)

    if removed:
        status = "not_comparable" if not retained else "partially_contaminated"
    elif any(item["severity"] == "warning" for item in reasons):
        status = "conditional"
    else:
        status = "comparable"
    return {
        "status": status,
        "comparison_corridors": list(comparison_corridors),
        "retained_corridors": retained,
        "removed_corridors": removed,
        "reasons": reasons,
    }


def _unreferenced_measures(
    inputs: StudyInputs, referenced: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    known = {str(item["measure_id"]) for item in referenced}
    return [
        {
            "measure_id": measure.measure_id,
            "activation_date": measure.activation_date.isoformat(),
            "scope_corridors": list(measure.scope_corridors),
        }
        for measure in inputs.measures.values()
        if measure.measure_id not in known
    ]


def _coverage_shift(pre: CorridorPeriodStats, post: CorridorPeriodStats) -> Decimal | None:
    if pre.counter_coverage_min is None or post.counter_coverage_min is None:
        return None
    return abs(post.counter_coverage_min - pre.counter_coverage_min)


def _corridor_stops(inputs: StudyInputs, corridor_id: str, day: date) -> set[str]:
    corridor = inputs.corridors[corridor_id]
    return {
        segment.stop_id
        for segment in inputs.network
        if segment.area_id == corridor.area_id and segment.valid_on(day)
    }


def _representativeness(
    surveys: Mapping[tuple[str, str, str, str], EffectiveSurvey],
    study_id: str,
    corridors: Sequence[str],
    period_ids: Sequence[str],
) -> tuple[dict[str, object], list[Limitation]]:
    limitations: list[Limitation] = []
    rows: list[dict[str, object]] = []
    max_gap = ZERO
    min_coverage: Decimal | None = None
    missing: list[str] = []

    for corridor_id in corridors:
        for period_id in period_ids:
            records = [
                survey
                for (candidate_study, candidate_corridor, candidate_period, _group), survey in surveys.items()
                if candidate_study == study_id and candidate_corridor == corridor_id and candidate_period == period_id
            ]
            population = sum(record.population_n for record in records)
            sample = sum(record.sample_n for record in records)
            if not records:
                missing.append(f"{corridor_id}/{period_id}")
                limitations.append(
                    Limitation(
                        "SURVEY_MISSING",
                        "blocking",
                        f"走廊 {corridor_id} 观察期 {period_id} 没有任何分群调查，覆盖与使用率无法估计。",
                        (corridor_id, period_id),
                    )
                )
                continue
            for record in records:
                population_share = Decimal(record.population_n) / Decimal(population)
                sample_share = Decimal(record.sample_n) / Decimal(sample) if sample else ZERO
                gap = sample_share - population_share
                if abs(gap) > max_gap:
                    max_gap = abs(gap)
                if min_coverage is None or record.coverage < min_coverage:
                    min_coverage = record.coverage
                rows.append(
                    {
                        "corridor_id": corridor_id,
                        "period_id": period_id,
                        "group_id": record.group_id,
                        "sample_n": record.sample_n,
                        "population_n": record.population_n,
                        "coverage": f"{record.coverage:.4f}",
                        "population_share": f"{population_share:.4f}",
                        "sample_share": f"{sample_share:.4f}",
                        "share_gap": f"{gap:.4f}",
                        "amended": record.amended,
                    }
                )
                if abs(gap) > Decimal("0.05"):
                    limitations.append(
                        Limitation(
                            "SURVEY_GROUP_UNDERREPRESENTED" if gap < 0 else "SURVEY_GROUP_OVERREPRESENTED",
                            "warning",
                            f"{corridor_id} {period_id} 的 {record.group_id} 样本份额与人口份额相差 {gap:+.2%}，"
                            "分群结论的代表性受限。",
                            (corridor_id, period_id, record.group_id),
                        )
                    )
                if record.sample_n < 30:
                    limitations.append(
                        Limitation(
                            "SMALL_SAMPLE",
                            "warning",
                            f"{corridor_id} {period_id} 的 {record.group_id} 仅有 {record.sample_n} 个有效样本，"
                            "分群估计不确定性较大。",
                            (corridor_id, period_id, record.group_id),
                        )
                    )
            if sample == 0:
                limitations.append(
                    Limitation(
                        "SURVEY_ZERO_SAMPLE",
                        "warning",
                        f"{corridor_id} 观察期 {period_id} 的调查样本量为 0，使用率无法估计。",
                        (corridor_id, period_id),
                    )
                )

    # Groups present in one period but missing in the other make group-level
    # before/after comparison impossible.
    for corridor_id in corridors:
        groups = sorted(
            {
                group
                for (study, corridor, _period, group) in surveys
                if study == study_id and corridor == corridor_id
            }
        )
        for group in groups:
            present = [
                period_id
                for period_id in period_ids
                if (study_id, corridor_id, period_id, group) in surveys
            ]
            if len(present) < len(period_ids):
                missing_periods = sorted(set(period_ids) - set(present))
                limitations.append(
                    Limitation(
                        "SURVEY_GROUP_MISSING_PERIOD",
                        "warning",
                        f"走廊 {corridor_id} 的群体 {group} 在观察期 {', '.join(missing_periods)} 没有调查记录，"
                        "该群体的前后比较缺失。",
                        (corridor_id, group),
                    )
                )

    return (
        {
            "max_share_gap": f"{max_gap:.4f}",
            "min_coverage": None if min_coverage is None else f"{min_coverage:.4f}",
            "groups_missing_periods": missing,
            "rows": rows,
        },
        limitations,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate(
    inputs: StudyInputs,
    study_id: str | None = None,
    *,
    as_of: date | str | None = None,
    include_operational: bool = True,
) -> Evaluation:
    """Evaluate one study and return a fully explicit result object."""

    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    if as_of is None:
        latest = max(
            [period.end for period in inputs.periods.values()]
            + [amendment.effective_date for amendment in inputs.amendments]
        )
        as_of = latest

    study_ids = inputs.study_ids()
    if not study_ids:
        raise ValidationError("没有可评估的研究")
    if study_id is None:
        study_id = study_ids[0]
    if study_id not in study_ids:
        raise ValidationError(f"未知研究 {study_id}，可用研究: {', '.join(study_ids)}")

    windows = inputs.windows_for(study_id)
    treated_windows = sorted({window.corridor_id for window in windows if window.group_role == "treated"})
    comparison_windows = sorted({window.corridor_id for window in windows if window.group_role == "comparison"})
    if len(treated_windows) != 1:
        raise ValidationError(
            f"研究 {study_id} 需恰好一个 treated 走廊，实际为 {len(treated_windows)} 个: "
            f"{', '.join(treated_windows) or '无'}"
        )
    if not comparison_windows:
        raise ValidationError(f"研究 {study_id} 没有 comparison 走廊")
    treated_corridor = treated_windows[0]

    periods = _periods_for_study(inputs, study_id)
    if len(periods) < 2:
        raise ValidationError(f"研究 {study_id} 只有一个观察期，无法进行前后比较")
    pre_period, post_period = periods[0], periods[-1]

    limitations: list[Limitation] = []
    notes: list[str] = [
        "需求单位是行程：同一 journey_id 的多个路段只计一次，路段数不作为独立出行人数。",
        "使用率的分母采用同一走廊、同一观察期的调查总体量，属于估计假设，并在敏感性分析中检验。",
        "对照支持的变化为双重差分估计；观察变化减去该估计后剩余的部分列为无法解释。",
    ]
    if len(periods) > 2:
        limitations.append(
            Limitation(
                "MULTIPLE_PERIODS_COLLAPSED",
                "warning",
                f"研究 {study_id} 有 {len(periods)} 个观察期，本次仅比较最早与最晚两期，中间期未纳入。",
            )
        )


    surveys, survey_limitations = effective_surveys(inputs, as_of)
    limitations.extend(survey_limitations)

    assignments, assignment_limitations, counters = _assign_journeys(inputs, study_id, as_of, include_operational)
    limitations.extend(assignment_limitations)

    window_by_corridor_period = {
        (window.corridor_id, window.period_id): window for window in windows
    }
    stats: dict[tuple[str, str], CorridorPeriodStats] = {}
    for corridor_id in [treated_corridor, *comparison_windows]:
        for period in (pre_period, post_period):
            window = window_by_corridor_period.get((corridor_id, period.period_id))
            if window is None:
                limitations.append(
                    Limitation(
                        "STUDY_WINDOW_MISSING",
                        "blocking",
                        f"走廊 {corridor_id} 在观察期 {period.period_id} 缺少研究窗口登记，无法比较。",
                        (corridor_id, period.period_id),
                    )
                )
                continue
            stats[(corridor_id, period.period_id)] = _corridor_period_stats(
                inputs,
                study_id,
                period.period_id,
                corridor_id,
                window,
                surveys,
                assignments,
            )

    # Network version availability per window.
    for (corridor_id, period_id), window in window_by_corridor_period.items():
        period = inputs.periods[period_id]
        available = [
            segment
            for segment in inputs.network
            if segment.version == window.service_version and segment.overlaps_period(period)
        ]
        if not available:
            limitations.append(
                Limitation(
                    "NETWORK_VERSION_UNAVAILABLE",
                    "blocking",
                    f"走廊 {corridor_id} 观察期 {period_id} 声明的服务网络版本 {window.service_version} "
                    "没有在服务网络中登记，行程归属不可验证。",
                    (corridor_id, period_id),
                )
            )
        treated_stops = _corridor_stops(inputs, corridor_id, period.start)
        version_stops = {segment.stop_id for segment in available}
        if available and not treated_stops.issubset(version_stops):
            missing = sorted(treated_stops - version_stops)
            limitations.append(
                Limitation(
                    "NETWORK_VERSION_PARTIAL",
                    "warning",
                    f"走廊 {corridor_id} 观察期 {period_id} 的服务版本 {window.service_version} "
                    f"未覆盖站点 {', '.join(missing)}，这些站点的行程不按该版本归属。",
                    (corridor_id, period_id),
                )
            )

    # Observed off-version and relocation counts.
    total_off = sum(stat.off_version_journeys for stat in stats.values())
    total_relocated = sum(stat.relocated_journeys for stat in stats.values())
    if total_off:
        limitations.append(
            Limitation(
                "JOURNEY_OFF_SERVICE_VERSION",
                "warning",
                f"{total_off} 条行程的出发站点在当日不属于研究窗口声明的服务网络版本，"
                "其归属按现有网络记录推断，敏感性分析中剔除。",
            )
        )
    # Relocation limitations are evaluated after comparability, because a
    # relocation only invalidates the estimate when it touches a corridor that
    # still contributes to it.
    for change in inputs.network_changes:
        if change.stop_id in {segment.stop_id for segment in inputs.network} and (
            pre_period.start <= change.effective_date <= post_period.end
        ):
            limitations.append(
                Limitation(
                    "NETWORK_CHANGE_IN_WINDOW",
                    "warning",
                    f"站点 {change.stop_id} 于 {change.effective_date.isoformat()} 发生网络变更"
                    f"（{change.changed_fields}；{change.reason}），相关行程的走廊归属需复核。",
                    (change.stop_id,),
                    True,
                )
            )

    # Treated-corridor version continuity: if the service version in the post
    # window includes only segments that do not overlap the baseline, the
    # comparison is really a network redesign, not a measure effect.
    for corridor_id in [treated_corridor]:
        version_by_period = {
            window.period_id: window.service_version
            for window in windows
            if window.corridor_id == corridor_id
            and window.period_id in {pre_period.period_id, post_period.period_id}
        }
        if len(set(version_by_period.values())) > 1:
            limitations.append(
                Limitation(
                    "TREATED_VERSION_CHANGED",
                    "info",
                    f"处理走廊 {corridor_id} 的服务网络版本由 "
                    f"{version_by_period.get(pre_period.period_id)} 变为 "
                    f"{version_by_period.get(post_period.period_id)}，措施与网络版本变化同时发生。",
                    (corridor_id,),
                )
            )

    # Measures and windows for the report.
    measure_rows: list[dict[str, object]] = []
    used_measure_ids = sorted({item for window in windows for item in window.measure_ids})
    for measure_id in used_measure_ids:
        measure = inputs.measures[measure_id]
        measure_rows.append(
            {
                "measure_id": measure.measure_id,
                "name": measure.name,
                "kind": measure.kind,
                "scope_corridors": list(measure.scope_corridors),
                "activation_date": measure.activation_date.isoformat(),
            }
        )
        for window in windows:
            if measure_id not in window.measure_ids:
                continue
            period = inputs.periods[window.period_id]
            if period.start < measure.activation_date <= period.end:
                limitations.append(
                    Limitation(
                        "PERIOD_CROSSES_ACTIVATION",
                        "warning",
                        f"研究 {study_id} 的观察期 {period.period_id} 跨越措施 {measure_id} 的启用日"
                        f" {measure.activation_date.isoformat()}，期间界定需复核。",
                        (window.corridor_id, period.period_id),
                    )
                )

    # Comparability.
    comparability = _comparability(
        inputs,
        study_id,
        treated_corridor,
        comparison_windows,
        pre_period,
        post_period,
        stats,
        [*measure_rows, *_unreferenced_measures(inputs, measure_rows)],
        limitations,
    )
    retained_comparisons = list(comparability["retained_corridors"])
    if len(comparison_windows) > 1:
        limitations.append(
            Limitation(
                "POOLED_COMPARISON",
                "info",
                f"登记 {len(comparison_windows)} 条对照走廊（{', '.join(comparison_windows)}）；"
                f"其中 {len(comparison_windows) - len(retained_comparisons)} 条因不可比被移出，"
                f"实际参与汇总 {len(retained_comparisons)} 条。",
                tuple(comparison_windows),
            )
        )
    for reason in comparability["reasons"]:
        if reason["severity"] != "blocking":
            continue
        # A contaminated corridor is a blocking defect for that corridor; if a
        # clean comparison remains, the study itself stays reviewable.
        severity = "warning" if retained_comparisons else "blocking"
        reason["severity"] = severity
        limitations.append(
            Limitation(
                reason["code"],
                severity,
                reason["message"],
                (str(reason.get("corridor_id", "")),),
                True,
            )
        )
    if comparability["removed_corridors"]:
        removed_ids = ", ".join(str(item["corridor_id"]) for item in comparability["removed_corridors"])
        limitations.append(
            Limitation(
                "COMPARISON_CORRIDOR_REMOVED",
                "warning" if retained_comparisons else "blocking",
                f"对照走廊 {removed_ids} 不再满足未受影响的参照条件，已从对照汇总中移出"
                + ("" if retained_comparisons else "；已无可用对照，无法进行对照比较")
                + "。",
                tuple(str(item["corridor_id"]) for item in comparability["removed_corridors"]),
                True,
            )
        )
    if not retained_comparisons:
        limitations.append(
            Limitation(
                "NO_VALID_COMPARISON",
                "blocking",
                "没有任何对照走廊在观察期内保持未受影响，前后总量变化不能支撑因果判断。",
            )
        )

    contributing = {treated_corridor, *retained_comparisons}
    relocated_contributing = sum(
        stat.relocated_journeys
        for (corridor_id, _period_id), stat in stats.items()
        if corridor_id in contributing
    )
    relocated_outside = counters.get("relocated_outside_corridor", 0)
    if relocated_contributing:
        limitations.append(
            Limitation(
                "STOP_RELOCATED_IN_WINDOW",
                "blocking",
                f"{relocated_contributing} 条行程的出发站点在参与估计的走廊内于观察期发生搬迁或区域调整，"
                "人群归属与估计范围已被改变，必须重新审阅后才能沿用本次结论。",
                tuple(sorted(contributing)),
                True,
            )
        )
    if relocated_outside:
        limitations.append(
            Limitation(
                "STOP_RELOCATED_OUT_OF_SCOPE",
                "warning",
                f"{relocated_outside} 条行程因站点在观察期内迁出而不再落入任何研究走廊；"
                "这部分客流已从估计范围消失，需说明其去向并重新审阅。",
                (),
                True,
            )
        )

    # Coverage / representativeness.  Contaminated controls are still shown so
    # their survey coverage is not silently dropped, but they no longer carry
    # any weight in the estimate.
    representativeness, rep_limitations = _representativeness(
        surveys,
        study_id,
        [treated_corridor, *comparison_windows],
        [pre_period.period_id, post_period.period_id],
    )
    limitations.extend(rep_limitations)

    # Per-corridor counter breadth and coverage shifts.
    for (corridor_id, period_id), stat in stats.items():
        period = inputs.periods[period_id]
        window = window_by_corridor_period.get((corridor_id, period_id))
        if window is None:
            continue
        expected_stops = _corridor_stops(inputs, corridor_id, period.start)
        if stat.counter_stops and not expected_stops.issubset(set(stat.counter_stops)):
            missing = sorted(expected_stops - set(stat.counter_stops))
            limitations.append(
                Limitation(
                    "COUNTER_PARTIAL_COVERAGE",
                    "warning",
                    f"走廊 {corridor_id} 观察期 {period_id} 的计数器未覆盖站点 {', '.join(missing)}，"
                    "计数变化只代表被观测站点。",
                    (corridor_id, period_id),
                )
            )
        if not stat.counter_stops:
            limitations.append(
                Limitation(
                    "COUNTER_MISSING",
                    "warning",
                    f"走廊 {corridor_id} 观察期 {period_id} 没有计数器记录，客流变化只能由抽样行程推断。",
                    (corridor_id, period_id),
                )
            )

    # Effects on the survey-based usage rate.
    effects: list[Effect] = []
    treated_pair = _pair_effect(stats, treated_corridor, pre_period, post_period)
    comparison_pairs = {
        corridor_id: _pair_effect(stats, corridor_id, pre_period, post_period)
        for corridor_id in retained_comparisons
    }
    usable_pairs = [
        (pair[0], pair[1]) for pair in comparison_pairs.values() if pair is not None
    ]
    if treated_pair is not None and usable_pairs:
        treated_change, pre_stats, post_stats = treated_pair
        comparison_change = _pooled_comparison_change("usage_rate_per_1000", usable_pairs)
        effects.append(
            _effect(
                "usage_rate_per_1000",
                treated_change,
                comparison_change,
                "主要估计：按行程加权的每千人使用率；对照变化按观察前人口加权汇总。",
            )
        )

    # Counter cross-check on relative change.  No confidence interval: this
    # only checks whether the direction agrees with the travel-chain estimate.
    counter_treated = _counter_change(stats, treated_corridor, pre_period, post_period)
    counter_comparisons = [
        result
        for corridor_id in retained_comparisons
        if (result := _counter_change(stats, corridor_id, pre_period, post_period)) is not None
    ]
    if counter_treated is not None and counter_comparisons:
        treated_relative = counter_treated.relative
        comparison_relative = sum(
            (result.relative for result in counter_comparisons), ZERO
        ) / Decimal(len(counter_comparisons))
        did = treated_relative - comparison_relative
        effects.append(
            Effect(
                "counter_relative_change",
                Change(
                    "counter_relative_change",
                    treated_corridor,
                    pre_period.period_id,
                    post_period.period_id,
                    None,
                    None,
                    treated_relative,
                    treated_relative,
                    None,
                ),
                Change(
                    "counter_relative_change",
                    "comparison",
                    pre_period.period_id,
                    post_period.period_id,
                    None,
                    None,
                    comparison_relative,
                    comparison_relative,
                    None,
                ),
                did,
                None,
                None,
                None,
                treated_relative - did,
                False,
                "计数器交叉核验：覆盖率校正后的计数相对变化；无置信区间，仅作方向核验。",
            )
        )

    if len(counter_comparisons) < len(retained_comparisons) and retained_comparisons:
        limitations.append(
            Limitation(
                "COUNTER_COMPARISON_INCOMPLETE",
                "info",
                "并非所有对照走廊都有可用的计数器记录，计数器交叉核验的对照口径不完整。",
            )
        )

    # Sensitivity: each variant recomputes the primary estimate.
    sensitivity: list[dict[str, object]] = []
    base = effects[0] if effects else None
    for label, options in (
        ("exclude_off_version", {"exclude_off_version": True}),
        ("exclude_relocated", {"exclude_relocated": True}),
        ("base_survey_denominator", {"base_denominator": True}),
    ):
        alt_stats = _recompute_stats(
            inputs,
            study_id,
            [treated_corridor, *retained_comparisons],
            (pre_period, post_period),
            window_by_corridor_period,
            surveys,
            assignments,
            options,
        )
        alt_effect = _effect_from_stats(
            alt_stats,
            treated_corridor,
            retained_comparisons,
            pre_period,
            post_period,
        )
        sensitivity.append(
            {
                "variant": label,
                "did": None if alt_effect is None or alt_effect.did is None else f"{alt_effect.did:.4f}",
                "ci_low": None if alt_effect is None or alt_effect.ci_low is None else f"{alt_effect.ci_low:.4f}",
                "ci_high": None if alt_effect is None or alt_effect.ci_high is None else f"{alt_effect.ci_high:.4f}",
                "delta_vs_primary": None
                if alt_effect is None
                or alt_effect.did is None
                or base is None
                or base.did is None
                else f"{alt_effect.did - base.did:.4f}",
                "supports_measure_effect": None if alt_effect is None else alt_effect.supports_measure_effect,
                "note": "无法计算该口径。" if alt_effect is None else "",
            }
        )
    baseline_assignments, _baseline_limits, _ = _assign_journeys(
        inputs,
        study_id,
        as_of,
        include_operational,
        pin_stop_areas_to=pre_period.start,
    )
    baseline_stats = _recompute_stats(
        inputs,
        study_id,
        [treated_corridor, *retained_comparisons],
        (pre_period, post_period),
        window_by_corridor_period,
        surveys,
        baseline_assignments,
        {},
    )
    baseline_effect = _effect_from_stats(
        baseline_stats,
        treated_corridor,
        retained_comparisons,
        pre_period,
        post_period,
    )
    sensitivity.append(
        {
            "variant": "pin_stops_to_pre_period",
            "did": None if baseline_effect is None or baseline_effect.did is None else f"{baseline_effect.did:.4f}",
            "ci_low": None if baseline_effect is None or baseline_effect.ci_low is None else f"{baseline_effect.ci_low:.4f}",
            "ci_high": None if baseline_effect is None or baseline_effect.ci_high is None else f"{baseline_effect.ci_high:.4f}",
            "delta_vs_primary": None
            if baseline_effect is None
            or baseline_effect.did is None
            or base is None
            or base.did is None
            else f"{baseline_effect.did - base.did:.4f}",
            "supports_measure_effect": None if baseline_effect is None else baseline_effect.supports_measure_effect,
            "note": "把站点固定在观察前所属区域，用于检验站点搬迁对人群归属的影响。",
        }
    )

    if counter_treated is not None and counter_comparisons and len(effects) > 1:
        sensitivity.append(
            {
                "variant": "counter_relative",
                "did": None if effects[1].did is None else f"{effects[1].did:.4f}",
                "note": "计数器口径，与每千人使用率单位不同，仅作方向核验。",
            }
        )

    primary = effects[0] if effects else None
    recommendation = _recommendation(comparability, primary, limitations, representativeness)

    provenance = {
        "base_sources": inputs.sources,
        "operational_sources": inputs.operational_sources,
        "included_operational": include_operational,
        "operational_records_used": sum(
            1 for item in assignments if item.source.startswith("operational/")
        ),
        "journey_counter": counters,
        "as_of": as_of.isoformat(),
    }

    existing_decisions = [
        {
            "decision_id": decision.decision_id,
            "measure_id": decision.measure_id,
            "action": decision.action,
            "decided_at": decision.decided_at.isoformat(),
            "evidence_id": decision.evidence_id,
            "rationale": decision.rationale,
            "acknowledged_limitations": list(decision.acknowledged_limitations),
            "superseded_by": decision.superseded_by,
        }
        for decision in inputs.decisions
        if decision.measure_id in used_measure_ids
    ]

    if not any(effect.supports_measure_effect for effect in effects):
        notes.append("没有任何口径的对照支持变化在 95% 区间内明确大于 0，不能据此认定措施带来了增长。")

    return Evaluation(
        study_id=study_id,
        as_of=as_of,
        include_operational=include_operational,
        pre_period=pre_period.period_id,
        post_period=post_period.period_id,
        treated_corridor=treated_corridor,
        comparison_corridors=tuple(retained_comparisons),
        measures=tuple(measure_rows),
        windows=tuple(
            {
                "corridor_id": window.corridor_id,
                "group_role": window.group_role,
                "period_id": window.period_id,
                "measure_id": "|".join(window.measure_ids),
                "service_version": window.service_version,
            }
            for window in sorted(windows, key=lambda item: (item.corridor_id, item.period_id))
        ),
        observations=tuple(
            stats[key] for key in sorted(stats, key=lambda item: (item[0], item[1]))
        ),
        representativeness=representativeness,
        comparability=comparability,
        effects=tuple(effects),
        sensitivity=tuple(sensitivity),
        limitations=tuple(_dedupe_limitations(limitations)),
        recommendation=recommendation,
        provenance=provenance,
        existing_decisions=tuple(existing_decisions),
        notes=tuple(notes),
    )


def _dedupe_limitations(limitations: Iterable[Limitation]) -> list[Limitation]:
    seen: set[tuple[str, str]] = set()
    result: list[Limitation] = []
    for limitation in limitations:
        key = (limitation.code, limitation.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(limitation)
    severity_order = {"blocking": 0, "warning": 1, "info": 2}
    return sorted(result, key=lambda item: (severity_order[item.severity], item.code, item.message))


def _pair_effect(
    stats: Mapping[tuple[str, str], CorridorPeriodStats],
    corridor_id: str,
    pre_period: Period,
    post_period: Period,
) -> tuple[Change, CorridorPeriodStats, CorridorPeriodStats] | None:
    pre = stats.get((corridor_id, pre_period.period_id))
    post = stats.get((corridor_id, post_period.period_id))
    if pre is None or post is None:
        return None
    change = _change("usage_rate_per_1000", pre, post, pre.rate_per_1000, post.rate_per_1000)
    return change, pre, post


def _counter_change(
    stats: Mapping[tuple[str, str], CorridorPeriodStats],
    corridor_id: str,
    pre_period: Period,
    post_period: Period,
) -> Change | None:
    pre = stats.get((corridor_id, pre_period.period_id))
    post = stats.get((corridor_id, post_period.period_id))
    if pre is None or post is None:
        return None
    if pre.counter_adjusted is None or post.counter_adjusted is None or pre.counter_adjusted == 0:
        return None
    relative = (post.counter_adjusted - pre.counter_adjusted) / pre.counter_adjusted
    return Change(
        "counter_relative_change",
        corridor_id,
        pre_period.period_id,
        post_period.period_id,
        pre.counter_adjusted,
        post.counter_adjusted,
        post.counter_adjusted - pre.counter_adjusted,
        relative,
        None,
    )


def _recompute_stats(
    inputs: StudyInputs,
    study_id: str,
    corridors: Sequence[str],
    periods: Sequence[Period],
    window_by_corridor_period: Mapping[tuple[str, str], StudyWindow],
    surveys: Mapping[tuple[str, str, str, str], EffectiveSurvey],
    assignments: Sequence[JourneyAssignment],
    options: Mapping[str, bool],
) -> dict[tuple[str, str], CorridorPeriodStats]:
    stats: dict[tuple[str, str], CorridorPeriodStats] = {}
    for corridor_id in corridors:
        for period in periods:
            window = window_by_corridor_period.get((corridor_id, period.period_id))
            if window is None:
                continue
            stats[(corridor_id, period.period_id)] = _corridor_period_stats(
                inputs,
                study_id,
                period.period_id,
                corridor_id,
                window,
                surveys,
                assignments,
                exclude_off_version=bool(options.get("exclude_off_version")),
                exclude_relocated=bool(options.get("exclude_relocated")),
                base_denominator=bool(options.get("base_denominator")),
            )
    return stats


def _effect_from_stats(
    stats: Mapping[tuple[str, str], CorridorPeriodStats],
    treated_corridor: str,
    comparison_corridors: Sequence[str],
    pre_period: Period,
    post_period: Period,
) -> Effect | None:
    treated_pair = _pair_effect(stats, treated_corridor, pre_period, post_period)
    comparison_pairs = [
        (pair[0], pair[1])
        for corridor_id in comparison_corridors
        if (pair := _pair_effect(stats, corridor_id, pre_period, post_period)) is not None
    ]
    if treated_pair is None or not comparison_pairs:
        return None
    comparison_change = _pooled_comparison_change("usage_rate_per_1000", comparison_pairs)
    return _effect("usage_rate_per_1000", treated_pair[0], comparison_change, "敏感性分析")


def _recommendation(
    comparability: Mapping[str, object],
    primary: Effect | None,
    limitations: Sequence[Limitation],
    representativeness: Mapping[str, object],
) -> dict[str, object]:
    blocking = [limitation for limitation in limitations if limitation.severity == "blocking"]
    reviews = [limitation for limitation in limitations if limitation.review_required]
    reasons: list[str] = []
    if comparability["status"] == "not_comparable":
        reasons.append("对照走廊已不具备未受影响的参照条件")
    if blocking:
        reasons.append(f"存在 {len(blocking)} 项阻断性限制，结论不足以支持扩大投入")
        return {"direction": "defer", "reasons": reasons}
    if primary is None or primary.did is None:
        reasons.append("主要对照估计不可用")
        return {"direction": "defer", "reasons": reasons}
    if primary.supports_measure_effect and reviews:
        reasons.append("主要对照估计在 95% 区间内明确大于 0")
        reasons.append(
            "但仍有需重新审阅的事项（"
            + ", ".join(sorted({limitation.code for limitation in reviews}))
            + "），在重新审阅前只能有条件地推进"
        )
        return {"direction": "adjust_or_continue", "reasons": reasons}
    if primary.supports_measure_effect:
        reasons.append("主要对照估计在 95% 区间内明确大于 0")
        return {"direction": "expand_candidate", "reasons": reasons}
    if primary.did > 0 and (primary.ci_low is None or primary.ci_low <= 0):
        reasons.append("观察到正向变化，但 95% 区间仍包含 0，证据只能支持继续试点或调整")
        return {"direction": "adjust_or_continue", "reasons": reasons}
    if primary.did <= 0:
        reasons.append("对照支持的变化不为正，现有证据不支持扩大")
        return {"direction": "defer_or_adjust", "reasons": reasons}
    return {"direction": "review", "reasons": reasons or ["需要人工复核"]}
