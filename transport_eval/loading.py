"""CSV input loading and contract validation.

The contract is intentionally explicit: every file is optional except the core
inputs, unknown columns produce warnings rather than silent acceptance, and
every error names the file, row, and field.  Records loaded from
``data/operational/`` are tagged with their source; if an operational file
re-uses an identifier from the frozen base input, loading fails instead of
letting later operational data rewrite earlier observations.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .errors import InputError, ValidationError
from .model import (
    Corridor,
    CounterRecord,
    Decision,
    Journey,
    Leg,
    Measure,
    NetworkChange,
    NetworkSegment,
    Period,
    StudyInputs,
    StudyWindow,
    SurveyAmendment,
    SurveyRecord,
    parse_date,
    parse_datetime,
)

SCHEMA_FIELDS: dict[str, tuple[str, ...]] = {
    "periods.csv": ("period_id", "start", "end"),
    "corridors.csv": ("corridor_id", "name", "area_id"),
    "measures.csv": ("measure_id", "name", "kind", "scope_corridors", "activation_date"),
    "study_windows.csv": ("study_id", "corridor_id", "group_role", "period_id", "measure_id", "service_version"),
    "network.csv": ("stop_id", "route_id", "version", "valid_from", "valid_to", "service_hours", "area_id"),
    "trip_legs.csv": (
        "journey_id",
        "leg_no",
        "mode",
        "from_stop",
        "to_stop",
        "depart_at",
        "person_group",
        "sample_weight",
    ),
    "surveys_measures.csv": (
        "record_id",
        "study_id",
        "corridor_id",
        "period_id",
        "group_id",
        "sample_n",
        "population_n",
        "measure_id",
        "stage",
        "activated_at",
        "budget",
    ),
    "survey_amendments.csv": (
        "amendment_id",
        "record_id",
        "effective_date",
        "previous_sample_n",
        "new_sample_n",
        "previous_population_n",
        "new_population_n",
        "moved_from_group",
        "moved_to_group",
        "moved_count",
        "reason",
    ),
    "network_changes.csv": (
        "change_id",
        "stop_id",
        "effective_date",
        "from_area",
        "to_area",
        "changed_fields",
        "reason",
    ),
    "counts.csv": (
        "count_id",
        "study_id",
        "corridor_id",
        "period_id",
        "stop_id",
        "observed_count",
        "coverage_ratio",
        "source",
    ),
    "decisions.csv": (
        "decision_id",
        "measure_id",
        "action",
        "decided_at",
        "evidence_id",
        "rationale",
        "acknowledged_limitations",
        "superseded_by",
    ),
}

REQUIRED_FILES = (
    "periods.csv",
    "corridors.csv",
    "measures.csv",
    "study_windows.csv",
    "network.csv",
    "trip_legs.csv",
    "surveys_measures.csv",
)

OPTIONAL_FILES = (
    "survey_amendments.csv",
    "network_changes.csv",
    "counts.csv",
    "decisions.csv",
)

GROUP_ROLES = ("treated", "comparison")
SURVEY_STAGES = ("planned", "baseline", "operating", "completed", "withdrawn")
DECISION_ACTIONS = ("expand", "adjust", "defer", "continue")
OPERATIONAL_DIR = "operational"
OPERATIONAL_PREFIX = OPERATIONAL_DIR + "/"


@dataclass(frozen=True)
class Row:
    source: str
    number: int
    values: dict[str, str]

    def where(self, field: str | None = None) -> str:
        suffix = f" 字段 {field}" if field else ""
        return f"{self.source} 第 {self.number} 行{suffix}"

    def get(self, field: str) -> str:
        return self.values.get(field, "").strip()

    def require(self, field: str) -> str:
        value = self.get(field)
        if not value:
            raise ValidationError(f"{self.where(field)}: 必填字段为空")
        return value


def _read_csv(path: Path, schema: Sequence[str], display: str, warnings: list[str]) -> list[Row]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ValidationError(f"{display}: 缺少表头")
            headers = [header.strip() for header in reader.fieldnames]
            if len(set(headers)) != len(headers):
                raise ValidationError(f"{display}: 表头存在重复列名")
            missing = [column for column in schema if column not in headers]
            if missing:
                raise ValidationError(f"{display}: 缺少列 {', '.join(missing)}")
            extra = [column for column in headers if column not in schema]
            if extra:
                warnings.append(f"{display}: 存在未使用列 {', '.join(extra)}")
            rows: list[Row] = []
            for number, raw in enumerate(reader, start=2):
                values = {(key or "").strip(): (value or "").strip() for key, value in raw.items()}
                if not any(values.values()):
                    continue
                rows.append(Row(display, number, values))
            return rows
    except OSError as exc:
        raise InputError(f"无法读取 {path}: {exc}") from exc
    except csv.Error as exc:
        raise InputError(f"{display}: CSV 解析失败: {exc}") from exc


def _parse_int(row: Row, field: str, *, minimum: int = 0) -> int:
    raw = row.require(field)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"{row.where(field)}: 需要整数，实际为 {raw!r}") from exc
    if value < minimum:
        raise ValidationError(f"{row.where(field)}: 不能小于 {minimum}")
    return value


def _parse_optional_int(row: Row, field: str, *, minimum: int = 0) -> int | None:
    if not row.get(field):
        return None
    return _parse_int(row, field, minimum=minimum)


def _parse_decimal(row: Row, field: str, *, positive: bool = False) -> Decimal:
    raw = row.require(field)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError(f"{row.where(field)}: 需要数字，实际为 {raw!r}") from exc
    if positive and value <= 0:
        raise ValidationError(f"{row.where(field)}: 必须大于 0")
    return value


def _parse_date_field(row: Row, field: str) -> date:
    raw = row.require(field)
    try:
        return parse_date(raw)
    except ValueError as exc:
        raise ValidationError(f"{row.where(field)}: 需要 YYYY-MM-DD 日期，实际为 {raw!r}") from exc


def _parse_optional_date(row: Row, field: str) -> date | None:
    if not row.get(field):
        return None
    return _parse_date_field(row, field)


def _parse_datetime_field(row: Row, field: str) -> datetime:
    raw = row.require(field)
    try:
        return parse_datetime(raw)
    except ValueError as exc:
        raise ValidationError(f"{row.where(field)}: 需要 ISO 日期时间，实际为 {raw!r}") from exc


def _split_list(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.replace("|", ";").split(";") if item.strip())


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recognised_paths(data_dir: Path) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        path = data_dir / name
        if path.is_file():
            paths.append((name, path))
    operational_dir = data_dir / OPERATIONAL_DIR
    if operational_dir.is_dir():
        for path in sorted(operational_dir.glob("*.csv")):
            if path.name in SCHEMA_FIELDS:
                paths.append((f"{OPERATIONAL_DIR}/{path.name}", path))
    return paths


def input_digests(data_dir: str | Path) -> dict[str, str]:
    """Return a stable SHA-256 digest for every recognised input file."""

    data_path = Path(data_dir)
    return dict(
        sorted(
            (display, _hash_file(path))
            for display, path in _recognised_paths(data_path)
        )
    )


def _load_periods(rows: Iterable[Row], warnings: list[str]) -> dict[str, Period]:
    periods: dict[str, Period] = {}
    for row in rows:
        period = Period(row.require("period_id"), _parse_date_field(row, "start"), _parse_date_field(row, "end"))
        if period.end < period.start:
            raise ValidationError(f"{row.where('end')}: 结束日期早于开始日期")
        if period.period_id in periods:
            raise ValidationError(f"{row.where('period_id')}: 重复的 period_id {period.period_id}")
        periods[period.period_id] = period
    if not periods:
        raise ValidationError("periods.csv: 至少需要一行观察期")
    ordered = sorted(periods.values(), key=lambda item: item.start)
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.overlaps(later):
            warnings.append(f"观察期 {earlier.period_id} 与 {later.period_id} 日期重叠")
    return periods


def _load_corridors(rows: Iterable[Row]) -> dict[str, Corridor]:
    corridors: dict[str, Corridor] = {}
    for row in rows:
        corridor = Corridor(row.require("corridor_id"), row.require("name"), row.require("area_id"))
        if corridor.corridor_id in corridors:
            raise ValidationError(f"{row.where('corridor_id')}: 重复的 corridor_id {corridor.corridor_id}")
        corridors[corridor.corridor_id] = corridor
    if not corridors:
        raise ValidationError("corridors.csv: 至少需要一行走廊")
    return corridors


def _load_measures(rows: Iterable[Row], corridors: Mapping[str, Corridor], warnings: list[str]) -> dict[str, Measure]:
    measures: dict[str, Measure] = {}
    for row in rows:
        scope = _split_list(row.get("scope_corridors"))
        unknown = [corridor for corridor in scope if corridor not in corridors]
        if unknown:
            raise ValidationError(f"{row.where('scope_corridors')}: 未知走廊 {', '.join(unknown)}")
        measure = Measure(
            row.require("measure_id"),
            row.require("name"),
            row.require("kind"),
            scope,
            _parse_date_field(row, "activation_date"),
        )
        if measure.measure_id in measures:
            raise ValidationError(f"{row.where('measure_id')}: 重复的 measure_id {measure.measure_id}")
        if not measure.scope_corridors:
            warnings.append(f"{row.where('scope_corridors')}: 措施未登记适用走廊")
        measures[measure.measure_id] = measure
    if not measures:
        raise ValidationError("measures.csv: 至少需要一行措施")
    return measures


def _load_windows(
    rows: Iterable[Row],
    corridors: Mapping[str, Corridor],
    periods: Mapping[str, Period],
    measures: Mapping[str, Measure],
    warnings: list[str],
) -> list[StudyWindow]:
    windows: list[StudyWindow] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        role = row.require("group_role")
        if role not in GROUP_ROLES:
            raise ValidationError(f"{row.where('group_role')}: 需要 treated 或 comparison")
        window = StudyWindow(
            row.require("study_id"),
            row.require("corridor_id"),
            role,
            row.require("period_id"),
            row.get("measure_id"),
            row.require("service_version"),
        )
        if window.corridor_id not in corridors:
            raise ValidationError(f"{row.where('corridor_id')}: 未知走廊 {window.corridor_id}")
        if window.period_id not in periods:
            raise ValidationError(f"{row.where('period_id')}: 未知观察期 {window.period_id}")
        unknown_measures = [item for item in window.measure_ids if item not in measures]
        if unknown_measures:
            raise ValidationError(f"{row.where('measure_id')}: 未知措施 {', '.join(unknown_measures)}")
        if role == "treated" and not window.measure_ids:
            warnings.append(
                f"{row.where('measure_id')}: 受措施走廊在观察期 {window.period_id} 未登记措施，"
                "按启用前基线处理"
            )
        if role == "comparison" and window.measure_ids:
            warnings.append(
                f"{row.where('measure_id')}: 对照走廊在观察窗口内登记了措施 {window.measure_id}，将触发可比性审查"
            )
        key = (window.study_id, window.corridor_id, window.period_id, role)
        if key in seen:
            raise ValidationError(f"{row.where('corridor_id')}: 同一研究、走廊、观察期与角色重复登记")
        seen.add(key)
        windows.append(window)
    if not windows:
        raise ValidationError("study_windows.csv: 至少需要一行研究窗口")
    return windows


def _load_network(rows: Iterable[Row], corridors: Mapping[str, Corridor], warnings: list[str]) -> list[NetworkSegment]:
    segments: list[NetworkSegment] = []
    seen: set[tuple[str, str, str]] = set()
    area_ids = {corridor.area_id for corridor in corridors.values()}
    for row in rows:
        segment = NetworkSegment(
            stop_id=row.require("stop_id"),
            route_id=row.require("route_id"),
            valid_from=_parse_date_field(row, "valid_from"),
            valid_to=_parse_optional_date(row, "valid_to"),
            service_hours=_parse_decimal(row, "service_hours"),
            area_id=row.require("area_id"),
            version=row.require("version"),
            source=row.source,
        )
        if segment.valid_to is not None and segment.valid_to < segment.valid_from:
            raise ValidationError(f"{row.where('valid_to')}: 失效日期早于生效日期")
        if segment.area_id not in area_ids:
            warnings.append(f"{row.where('area_id')}: 区域 {segment.area_id} 未对应任何走廊")
        key = (segment.stop_id, segment.route_id, segment.version)
        if key in seen:
            raise ValidationError(f"{row.where('version')}: 重复的站点线路版本")
        seen.add(key)
        segments.append(segment)
    if not segments:
        raise ValidationError("network.csv: 至少需要一行网络记录")
    return segments


def _load_journeys(rows: Iterable[Row], segments: Sequence[NetworkSegment], warnings: list[str]) -> dict[str, Journey]:
    grouped: dict[str, list[Leg]] = {}
    source_by_journey: dict[str, str] = {}
    for row in rows:
        leg = Leg(
            row.require("journey_id"),
            _parse_int(row, "leg_no", minimum=1),
            row.require("mode"),
            row.require("from_stop"),
            row.require("to_stop"),
            _parse_datetime_field(row, "depart_at"),
            row.require("person_group"),
            _parse_decimal(row, "sample_weight", positive=True),
            row.source,
        )
        prior_source = source_by_journey.setdefault(leg.journey_id, row.source)
        if prior_source != row.source:
            raise ValidationError(
                f"{row.where('journey_id')}: 行程 {leg.journey_id} 同时出现在 {prior_source} 与 {row.source}，"
                "运营资料不得覆盖冻结输入中的同一行程"
            )
        grouped.setdefault(leg.journey_id, []).append(leg)

    known_stops = {segment.stop_id for segment in segments}
    journeys: dict[str, Journey] = {}
    for journey_id, legs in grouped.items():
        legs.sort(key=lambda item: item.leg_no)
        numbers = [leg.leg_no for leg in legs]
        if len(numbers) != len(set(numbers)):
            raise ValidationError(f"trip_legs.csv: 行程 {journey_id} 存在重复路段编号")
        if numbers != list(range(1, len(numbers) + 1)):
            warnings.append(f"trip_legs.csv: 行程 {journey_id} 的路段编号不连续 {numbers}")
        groups = {leg.person_group for leg in legs}
        weights = {leg.sample_weight for leg in legs}
        if len(groups) != 1:
            raise ValidationError(f"trip_legs.csv: 行程 {journey_id} 的同一行程人群标签不一致 {sorted(groups)}")
        if len(weights) != 1:
            raise ValidationError(f"trip_legs.csv: 行程 {journey_id} 的同一行程样本权重不一致")
        for earlier, later in zip(legs, legs[1:]):
            if later.depart_at < earlier.depart_at:
                raise ValidationError(f"trip_legs.csv: 行程 {journey_id} 的路段出发时间倒序")
        for leg in legs:
            for stop in (leg.from_stop, leg.to_stop):
                if stop not in known_stops:
                    warnings.append(f"trip_legs.csv: 行程 {journey_id} 使用未登记站点 {stop}，将无法归属走廊")
        journeys[journey_id] = Journey(journey_id, legs[0].person_group, legs[0].sample_weight, tuple(legs))
    if not journeys:
        raise ValidationError("trip_legs.csv: 至少需要一条行程")
    return journeys


def _load_surveys(
    rows: Iterable[Row],
    windows: Sequence[StudyWindow],
    measures: Mapping[str, Measure],
    warnings: list[str],
) -> list[SurveyRecord]:
    study_keys = {(window.study_id, window.corridor_id, window.period_id) for window in windows}
    records: list[SurveyRecord] = []
    seen: set[str] = set()
    for row in rows:
        record = SurveyRecord(
            row.require("record_id"),
            row.require("study_id"),
            row.require("corridor_id"),
            row.require("period_id"),
            row.require("group_id"),
            _parse_int(row, "sample_n"),
            _parse_int(row, "population_n", minimum=1),
            row.get("measure_id"),
            row.require("stage"),
            _parse_optional_date(row, "activated_at"),
            _parse_optional_int(row, "budget"),
            row.source,
        )
        if record.record_id in seen:
            raise ValidationError(f"{row.where('record_id')}: 重复的调查记录 {record.record_id}")
        seen.add(record.record_id)
        if record.stage not in SURVEY_STAGES:
            raise ValidationError(f"{row.where('stage')}: 需要 {', '.join(SURVEY_STAGES)}")
        if (record.study_id, record.corridor_id, record.period_id) not in study_keys:
            raise ValidationError(f"{row.where('corridor_id')}: 调查记录未对应任何研究窗口")
        record_measures = _split_list(record.measure_id)
        unknown_measures = [item for item in record_measures if item not in measures]
        if unknown_measures:
            raise ValidationError(f"{row.where('measure_id')}: 未知措施 {', '.join(unknown_measures)}")
        if record.sample_n > record.population_n:
            warnings.append(f"{row.where('sample_n')}: 样本量大于总体量，请检查")
        if record.sample_n == 0:
            warnings.append(f"{row.where('sample_n')}: 该群体本期无有效样本")
        records.append(record)
    if not records:
        raise ValidationError("surveys_measures.csv: 至少需要一行分群调查")
    return records


def _load_amendments(
    rows: Iterable[Row], surveys: Sequence[SurveyRecord], warnings: list[str]
) -> list[SurveyAmendment]:
    by_id = {record.record_id: record for record in surveys}
    amendments: list[SurveyAmendment] = []
    seen: set[str] = set()
    for row in rows:
        amendment = SurveyAmendment(
            row.require("amendment_id"),
            row.require("record_id"),
            _parse_date_field(row, "effective_date"),
            _parse_int(row, "previous_sample_n"),
            _parse_int(row, "new_sample_n"),
            _parse_int(row, "previous_population_n", minimum=1),
            _parse_int(row, "new_population_n", minimum=1),
            row.get("moved_from_group"),
            row.get("moved_to_group"),
            _parse_int(row, "moved_count"),
            row.require("reason"),
            row.source,
        )
        if amendment.amendment_id in seen:
            raise ValidationError(f"{row.where('amendment_id')}: 重复的修订 {amendment.amendment_id}")
        seen.add(amendment.amendment_id)
        record = by_id.get(amendment.record_id)
        if record is None:
            raise ValidationError(f"{row.where('record_id')}: 未知调查记录 {amendment.record_id}")
        if (amendment.previous_sample_n, amendment.previous_population_n) != (
            record.sample_n,
            record.population_n,
        ):
            raise ValidationError(
                f"{row.where('previous_sample_n')}: 修订前数值与调查记录 {record.record_id} 不一致"
            )
        if amendment.new_sample_n > amendment.new_population_n:
            warnings.append(f"{row.where('new_sample_n')}: 修订后样本量大于总体量")
        if amendment.moved_count > amendment.new_sample_n:
            raise ValidationError(f"{row.where('moved_count')}: 迁移人数大于修订后样本量")
        if amendment.moved_count and not amendment.moved_to_group:
            warnings.append(f"{row.where('moved_to_group')}: 登记了人群迁移但未填写迁入群体")
        amendments.append(amendment)
    return amendments


def _load_network_changes(
    rows: Iterable[Row], segments: Sequence[NetworkSegment], warnings: list[str]
) -> list[NetworkChange]:
    stops = {segment.stop_id for segment in segments}
    changes: list[NetworkChange] = []
    seen: set[str] = set()
    for row in rows:
        change = NetworkChange(
            row.require("change_id"),
            row.require("stop_id"),
            _parse_date_field(row, "effective_date"),
            row.get("from_area"),
            row.get("to_area"),
            row.require("changed_fields"),
            row.require("reason"),
            row.source,
        )
        if change.change_id in seen:
            raise ValidationError(f"{row.where('change_id')}: 重复的网络变更 {change.change_id}")
        seen.add(change.change_id)
        if change.stop_id not in stops:
            warnings.append(f"{row.where('stop_id')}: 变更涉及未登记站点 {change.stop_id}")
        changes.append(change)
    return changes


def _load_counters(
    rows: Iterable[Row],
    windows: Sequence[StudyWindow],
    segments: Sequence[NetworkSegment],
    warnings: list[str],
) -> list[CounterRecord]:
    study_keys = {(window.study_id, window.corridor_id, window.period_id) for window in windows}
    stops = {segment.stop_id for segment in segments}
    counters: list[CounterRecord] = []
    seen: set[str] = set()
    for row in rows:
        coverage = _parse_decimal(row, "coverage_ratio")
        if not (Decimal("0") < coverage <= Decimal("1")):
            raise ValidationError(f"{row.where('coverage_ratio')}: 覆盖率需在 (0, 1] 区间，实际为 {coverage}")
        counter = CounterRecord(
            row.require("count_id"),
            row.require("study_id"),
            row.require("corridor_id"),
            row.require("period_id"),
            row.require("stop_id"),
            _parse_int(row, "observed_count"),
            coverage,
            row.get("source") or row.source,
        )
        if counter.count_id in seen:
            raise ValidationError(f"{row.where('count_id')}: 重复的计数记录 {counter.count_id}")
        seen.add(counter.count_id)
        if (counter.study_id, counter.corridor_id, counter.period_id) not in study_keys:
            raise ValidationError(f"{row.where('corridor_id')}: 计数记录未对应任何研究窗口")
        if counter.stop_id not in stops:
            warnings.append(f"{row.where('stop_id')}: 计数站点 {counter.stop_id} 未在服务网络中登记")
        counters.append(counter)
    return counters


def _load_decisions(
    rows: Iterable[Row], measures: Mapping[str, Measure], warnings: list[str]
) -> list[Decision]:
    decisions: list[Decision] = []
    seen: set[str] = set()
    for row in rows:
        action = row.require("action")
        if action not in DECISION_ACTIONS:
            raise ValidationError(f"{row.where('action')}: 需要 {', '.join(DECISION_ACTIONS)}")
        measure_id = row.require("measure_id")
        if measure_id not in measures:
            raise ValidationError(f"{row.where('measure_id')}: 未知措施 {measure_id}")
        decision = Decision(
            row.require("decision_id"),
            measure_id,
            action,
            _parse_datetime_field(row, "decided_at"),
            row.require("evidence_id"),
            row.require("rationale"),
            _split_list(row.get("acknowledged_limitations")),
            row.get("superseded_by"),
        )
        if decision.decision_id in seen:
            raise ValidationError(f"{row.where('decision_id')}: 重复的决定 {decision.decision_id}")
        seen.add(decision.decision_id)
        if not decision.acknowledged_limitations:
            warnings.append(f"{row.where('acknowledged_limitations')}: 决定未登记已确认的结论限制")
        decisions.append(decision)
    return decisions


def load_workspace(data_dir: str | Path) -> StudyInputs:
    """Load and validate every recognised input below ``data_dir``."""

    data_path = Path(data_dir)
    if not data_path.is_dir():
        raise InputError(f"输入目录不存在: {data_path}")

    warnings: list[str] = []
    sources: dict[str, str] = {}
    operational_sources: dict[str, str] = {}
    rows_by_schema: dict[str, list[Row]] = {name: [] for name in SCHEMA_FIELDS}

    for name in REQUIRED_FILES:
        path = data_path / name
        if not path.is_file():
            raise InputError(f"缺少必需输入文件: {path}")
        rows_by_schema[name].extend(_read_csv(path, SCHEMA_FIELDS[name], name, warnings))
        sources[name] = str(path)
    for name in OPTIONAL_FILES:
        path = data_path / name
        if path.is_file():
            rows_by_schema[name].extend(_read_csv(path, SCHEMA_FIELDS[name], name, warnings))
            sources[name] = str(path)

    operational_dir = data_path / OPERATIONAL_DIR
    if operational_dir.is_dir():
        for path in sorted(operational_dir.glob("*.csv")):
            if path.name not in SCHEMA_FIELDS:
                warnings.append(f"{OPERATIONAL_DIR}/{path.name}: 未识别的运营资料文件，已忽略")
                continue
            display = f"{OPERATIONAL_DIR}/{path.name}"
            rows_by_schema[path.name].extend(_read_csv(path, SCHEMA_FIELDS[path.name], display, warnings))
            operational_sources[display] = str(path)

    periods = _load_periods(rows_by_schema["periods.csv"], warnings)
    corridors = _load_corridors(rows_by_schema["corridors.csv"])
    measures = _load_measures(rows_by_schema["measures.csv"], corridors, warnings)
    windows = _load_windows(rows_by_schema["study_windows.csv"], corridors, periods, measures, warnings)
    network = _load_network(rows_by_schema["network.csv"], corridors, warnings)
    journeys = _load_journeys(rows_by_schema["trip_legs.csv"], network, warnings)
    surveys = _load_surveys(rows_by_schema["surveys_measures.csv"], windows, measures, warnings)
    amendments = _load_amendments(rows_by_schema["survey_amendments.csv"], surveys, warnings)
    network_changes = _load_network_changes(rows_by_schema["network_changes.csv"], network, warnings)
    counters = _load_counters(rows_by_schema["counts.csv"], windows, network, warnings)
    decisions = _load_decisions(rows_by_schema["decisions.csv"], measures, warnings)

    _validate_cross_references(periods, measures, windows, surveys, warnings)

    return StudyInputs(
        periods=periods,
        corridors=corridors,
        measures=measures,
        study_windows=windows,
        network=network,
        journeys=journeys,
        surveys=surveys,
        amendments=amendments,
        network_changes=network_changes,
        counters=counters,
        decisions=decisions,
        sources=sources,
        operational_sources=operational_sources,
        warnings=warnings,
    )


def _validate_cross_references(
    periods: Mapping[str, Period],
    measures: Mapping[str, Measure],
    windows: Sequence[StudyWindow],
    surveys: Sequence[SurveyRecord],
    warnings: list[str],
) -> None:
    used_measures = {item for window in windows for item in window.measure_ids}
    for measure in measures.values():
        if measure.measure_id not in used_measures:
            warnings.append(f"measures.csv: 措施 {measure.measure_id} 未出现在任何研究窗口")
    study_ids = sorted({window.study_id for window in windows})
    for study_id in study_ids:
        study_windows = [window for window in windows if window.study_id == study_id]
        roles = {window.group_role for window in study_windows}
        if roles != set(GROUP_ROLES):
            warnings.append(f"study_windows.csv: 研究 {study_id} 缺少 treated 或 comparison 窗口")
        if len({window.period_id for window in study_windows}) < 2:
            warnings.append(f"study_windows.csv: 研究 {study_id} 只有一个观察期，无法比较前后变化")
        for window in study_windows:
            if not any(
                survey.study_id == window.study_id
                and survey.corridor_id == window.corridor_id
                and survey.period_id == window.period_id
                for survey in surveys
            ):
                warnings.append(
                    f"surveys_measures.csv: 研究 {study_id} 走廊 {window.corridor_id} "
                    f"观察期 {window.period_id} 缺少分群调查"
                )
            if not window.measure_ids:
                continue
            period = periods[window.period_id]
            for measure_id in window.measure_ids:
                activation = measures[measure_id].activation_date
                if window.group_role == "treated" and period.start < activation <= period.end:
                    warnings.append(
                        f"study_windows.csv: 研究 {study_id} 的观察期 {window.period_id} "
                        f"跨越措施 {measure_id} 的启用日 {activation.isoformat()}，前后比较边界需复核"
                    )


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest_value(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
