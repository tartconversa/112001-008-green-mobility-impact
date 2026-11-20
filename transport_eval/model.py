"""Immutable records used by the evaluation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Period:
    period_id: str
    start: date
    end: date

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment.date() <= self.end

    def overlaps(self, other: "Period") -> bool:
        return not (self.end < other.start or other.end < self.start)


@dataclass(frozen=True)
class Corridor:
    corridor_id: str
    name: str
    area_id: str


@dataclass(frozen=True)
class Measure:
    measure_id: str
    name: str
    kind: str
    scope_corridors: tuple[str, ...]
    activation_date: date


@dataclass(frozen=True)
class StudyWindow:
    study_id: str
    corridor_id: str
    group_role: str
    period_id: str
    measure_id: str
    service_version: str

    @property
    def measure_ids(self) -> tuple[str, ...]:
        """One window may register a package of several measures."""

        return tuple(
            item.strip()
            for item in self.measure_id.replace("|", ";").split(";")
            if item.strip()
        )


@dataclass(frozen=True)
class NetworkSegment:
    stop_id: str
    route_id: str
    valid_from: date
    valid_to: date | None
    service_hours: Decimal
    area_id: str
    version: str
    source: str = "base"

    def valid_on(self, day: date) -> bool:
        if day < self.valid_from:
            return False
        return self.valid_to is None or day <= self.valid_to

    def overlaps_period(self, period: Period) -> bool:
        return self.valid_from <= period.end and (self.valid_to is None or self.valid_to >= period.start)


@dataclass(frozen=True)
class Leg:
    journey_id: str
    leg_no: int
    mode: str
    from_stop: str
    to_stop: str
    depart_at: datetime
    person_group: str
    sample_weight: Decimal
    source: str = "base"


@dataclass(frozen=True)
class Journey:
    journey_id: str
    person_group: str
    sample_weight: Decimal
    legs: tuple[Leg, ...]

    @property
    def depart_at(self) -> datetime:
        return self.legs[0].depart_at

    @property
    def leg_count(self) -> int:
        return len(self.legs)


@dataclass(frozen=True)
class SurveyRecord:
    record_id: str
    study_id: str
    corridor_id: str
    period_id: str
    group_id: str
    sample_n: int
    population_n: int
    measure_id: str
    stage: str
    activated_at: date | None
    budget: int | None
    source: str = "base"


@dataclass(frozen=True)
class SurveyAmendment:
    amendment_id: str
    record_id: str
    effective_date: date
    previous_sample_n: int
    new_sample_n: int
    previous_population_n: int
    new_population_n: int
    moved_from_group: str
    moved_to_group: str
    moved_count: int
    reason: str
    source: str = "base"


@dataclass(frozen=True)
class NetworkChange:
    change_id: str
    stop_id: str
    effective_date: date
    from_area: str
    to_area: str
    changed_fields: str
    reason: str
    source: str = "base"


@dataclass(frozen=True)
class CounterRecord:
    count_id: str
    study_id: str
    corridor_id: str
    period_id: str
    stop_id: str
    observed_count: int
    coverage_ratio: Decimal
    source: str = "base"


@dataclass(frozen=True)
class Decision:
    decision_id: str
    measure_id: str
    action: str
    decided_at: datetime
    evidence_id: str
    rationale: str
    acknowledged_limitations: tuple[str, ...]
    superseded_by: str = ""


@dataclass
class StudyInputs:
    periods: dict[str, Period]
    corridors: dict[str, Corridor]
    measures: dict[str, Measure]
    study_windows: list[StudyWindow]
    network: list[NetworkSegment]
    journeys: dict[str, Journey]
    surveys: list[SurveyRecord]
    amendments: list[SurveyAmendment]
    network_changes: list[NetworkChange]
    counters: list[CounterRecord]
    decisions: list[Decision]
    sources: dict[str, str]
    operational_sources: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def study_ids(self) -> list[str]:
        return sorted({window.study_id for window in self.study_windows})

    def windows_for(self, study_id: str) -> list[StudyWindow]:
        return [window for window in self.study_windows if window.study_id == study_id]

    def surveys_in(self, study_id: str, corridor_id: str, period_id: str) -> list[SurveyRecord]:
        return [
            record
            for record in self.surveys
            if record.study_id == study_id
            and record.corridor_id == corridor_id
            and record.period_id == period_id
        ]

    def survey_for(self, study_id: str, corridor_id: str, period_id: str, group_id: str) -> SurveyRecord | None:
        matches = [
            record
            for record in self.surveys_in(study_id, corridor_id, period_id)
            if record.group_id == group_id
        ]
        return matches[-1] if matches else None



def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


