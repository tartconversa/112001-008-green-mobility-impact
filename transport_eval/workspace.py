"""Evidence snapshots and the decision ledger.

A decision is recorded against a *frozen* evidence snapshot (a pinned set of
input digests plus the evaluation result).  Later operational input can be
loaded and re-evaluated, but it can never rewrite the snapshot a decision was
approved on: the digest check fails loudly if any pinned file changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .errors import IntegrityError, ValidationError
from .estimation import Evaluation, evaluate
from .loading import digest_value, input_digests, load_workspace
from .model import StudyInputs

SNAPSHOT_SCHEMA = "transport-eval/evidence-snapshot-v1"
LEDGER_SCHEMA = "transport-eval/decision-ledger-v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IntegrityError(f"无法读取 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"{path} 不是有效的 JSON: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_id: str
    created_at: str
    study_id: str
    as_of: str
    include_operational: bool
    digests: dict[str, str]
    evaluation: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "evidence_id": self.evidence_id,
            "created_at": self.created_at,
            "study_id": self.study_id,
            "as_of": self.as_of,
            "include_operational": self.include_operational,
            "digests": dict(self.digests),
            "evaluation": self.evaluation,
        }


def _snapshot_evaluation(evaluation: Evaluation) -> dict[str, object]:
    payload = evaluation.as_dict()
    payload.pop("provenance", None)
    return payload


class StudyWorkspace:
    """A data directory plus a directory of frozen evidence and decisions."""

    def __init__(self, data_dir: str | Path, workspace_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.workspace_dir = Path(workspace_dir) if workspace_dir else self.data_dir / "workspace"

    # -- evaluation -------------------------------------------------------
    def load(self) -> StudyInputs:
        return load_workspace(self.data_dir)

    def evaluate(
        self,
        study_id: str | None = None,
        *,
        as_of: date | str | None = None,
        include_operational: bool = True,
        inputs: StudyInputs | None = None,
    ) -> Evaluation:
        return evaluate(
            inputs or self.load(),
            study_id,
            as_of=as_of,
            include_operational=include_operational,
        )

    def digests(self) -> dict[str, str]:
        return input_digests(self.data_dir)

    # -- evidence snapshots ----------------------------------------------
    @property
    def evidence_dir(self) -> Path:
        return self.workspace_dir / "evidence"

    @property
    def decisions_path(self) -> Path:
        return self.workspace_dir / "decisions.json"

    def freeze(
        self,
        study_id: str,
        *,
        as_of: date | str | None = None,
        include_operational: bool = True,
    ) -> EvidenceSnapshot:
        evaluation = self.evaluate(study_id, as_of=as_of, include_operational=include_operational)
        digests = self.digests()
        payload = _snapshot_evaluation(evaluation)
        evidence_id = "EV-" + digest_value(
            {
                "study_id": study_id,
                "as_of": evaluation.as_of.isoformat(),
                "include_operational": include_operational,
                "digests": digests,
            }
        )[:16]
        snapshot = EvidenceSnapshot(
            evidence_id,
            _now(),
            study_id,
            evaluation.as_of.isoformat(),
            include_operational,
            digests,
            payload,
        )
        _write_json(self.evidence_dir / f"{evidence_id}.json", snapshot.as_dict())
        return snapshot

    def load_snapshot(self, evidence_id: str) -> EvidenceSnapshot:
        path = self.evidence_dir / f"{evidence_id}.json"
        if not path.is_file():
            raise ValidationError(f"未知证据编号 {evidence_id}")
        data = _read_json(path)
        if data.get("schema") != SNAPSHOT_SCHEMA:
            raise IntegrityError(f"{path.name} 的 schema 不是 {SNAPSHOT_SCHEMA}")
        return EvidenceSnapshot(
            str(data["evidence_id"]),
            str(data["created_at"]),
            str(data["study_id"]),
            str(data["as_of"]),
            bool(data["include_operational"]),
            {str(key): str(value) for key, value in dict(data["digests"]).items()},
            dict(data["evaluation"]),
        )

    def verify_snapshot(self, evidence_id: str) -> tuple[str, ...]:
        """Return the pinned files whose current digest differs from the snapshot.

        An empty tuple means the frozen evidence is byte-identical to the input
        it was approved on.  Missing files also count as drift.
        """

        snapshot = self.load_snapshot(evidence_id)
        current = self.digests()
        drifted: list[str] = []
        for name, digest in snapshot.digests.items():
            if current.get(name) != digest:
                drifted.append(name)
        return tuple(sorted(drifted))

    def new_inputs(self, evidence_id: str) -> tuple[str, ...]:
        """Input files present now but absent when the snapshot was frozen.

        New operational material is expected after a decision; it must enter
        the next evaluation, but it is reported separately so it is never
        mistaken for evidence the decision was approved on.
        """

        snapshot = self.load_snapshot(evidence_id)
        return tuple(sorted(set(self.digests()) - set(snapshot.digests)))

    # -- decisions --------------------------------------------------------
    def _load_ledger(self) -> dict[str, object]:
        if not self.decisions_path.is_file():
            return {"schema": LEDGER_SCHEMA, "entries": []}
        data = _read_json(self.decisions_path)
        if data.get("schema") != LEDGER_SCHEMA:
            raise IntegrityError(f"{self.decisions_path} 的 schema 不是 {LEDGER_SCHEMA}")
        return data

    def decisions(self) -> list[dict[str, object]]:
        return list(self._load_ledger()["entries"])

    def record_decision(
        self,
        evidence_id: str,
        *,
        action: str,
        rationale: str,
        acknowledged_limitations: Sequence[str] = (),
        supersedes: str | None = None,
        decided_by: str = "",
        decided_at: datetime | None = None,
    ) -> dict[str, object]:
        if action not in ("expand", "adjust", "defer", "continue"):
            raise ValidationError(f"未知决定动作 {action}")
        if not rationale.strip():
            raise ValidationError("决定需要填写理由")
        snapshot = self.load_snapshot(evidence_id)
        drifted = self.verify_snapshot(evidence_id)
        if drifted:
            raise IntegrityError(
                "冻结证据对应的输入已变化（" + ", ".join(drifted) + "）；"
                "不能在此证据上登记决定，请先重新生成并冻结证据。"
            )
        limitations = list(snapshot.evaluation.get("limitations", []))
        review_codes = {item["code"] for item in limitations if item.get("review_required")}
        declared = set(acknowledged_limitations)
        missing = sorted(review_codes - declared)
        if missing:
            raise ValidationError(
                "以下需要复核的限制未被确认，不能登记决定: " + ", ".join(missing)
            )
        ledger = self._load_ledger()
        entries = list(ledger["entries"])
        if supersedes and supersedes not in {entry["decision_id"] for entry in entries}:
            raise ValidationError(f"被替代的决定 {supersedes} 不存在")
        decision_id = "D-" + digest_value(
            {
                "evidence_id": evidence_id,
                "action": action,
                "rationale": rationale,
                "at": (decided_at or datetime.now(timezone.utc)).isoformat(),
                "prior": len(entries),
            }
        )[:12]
        entry = {
            "decision_id": decision_id,
            "evidence_id": evidence_id,
            "study_id": snapshot.study_id,
            "measure_ids": sorted(
                {measure["measure_id"] for measure in snapshot.evaluation.get("measures", [])}
            ),
            "action": action,
            "rationale": rationale,
            "decided_at": (decided_at or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(),
            "decided_by": decided_by,
            "acknowledged_limitations": sorted(declared),
            "evidence_as_of": snapshot.as_of,
            "evidence_include_operational": snapshot.include_operational,
            "evidence_digests": snapshot.digests,
            "snapshot_digest": digest_value(snapshot.evaluation),
            "conclusion_grade": snapshot.evaluation.get("conclusion_grade"),
            "supersedes": supersedes or "",
            "superseded_by": "",
            "review_triggers": _review_triggers(snapshot.evaluation),
        }
        if supersedes:
            for prior in entries:
                if prior["decision_id"] == supersedes:
                    prior["superseded_by"] = decision_id
        entries.append(entry)
        ledger["entries"] = entries
        _write_json(self.decisions_path, ledger)
        return entry

    def compare_with_snapshot(
        self,
        evidence_id: str,
        *,
        as_of: date | str | None = None,
        include_operational: bool = True,
    ) -> dict[str, object]:
        """Show what changed in the evidence since a snapshot was frozen."""

        snapshot = self.load_snapshot(evidence_id)
        current = self.evaluate(
            snapshot.study_id,
            as_of=as_of or snapshot.as_of,
            include_operational=include_operational,
        )
        current_codes = set(current.limitation_codes)
        prior_codes = {
            str(item["code"]) for item in snapshot.evaluation.get("limitations", [])
        }
        return {
            "evidence_id": evidence_id,
            "input_drift": list(self.verify_snapshot(evidence_id)),
            "new_inputs_since_freeze": list(self.new_inputs(evidence_id)),
            "new_limitations": sorted(current_codes - prior_codes),
            "resolved_limitations": sorted(prior_codes - current_codes),
            "prior_conclusion_grade": snapshot.evaluation.get("conclusion_grade"),
            "current_conclusion_grade": current.conclusion_grade,
            "primary_effect_prior": (
                snapshot.evaluation.get("effects", [{}])[0].get("did")
                if snapshot.evaluation.get("effects")
                else None
            ),
            "primary_effect_current": (
                current.effects[0].as_dict().get("did") if current.effects else None
            ),
        }


def _review_triggers(evaluation: Mapping[str, object]) -> list[dict[str, object]]:
    """Input-change classes that must force a re-review of this decision."""

    triggers: list[dict[str, object]] = []
    seen: set[str] = set()
    for limitation in evaluation.get("limitations", []):
        if not limitation.get("review_required"):
            continue
        code = str(limitation["code"])
        if code in seen:
            continue
        seen.add(code)
        triggers.append(
            {
                "code": code,
                "severity": limitation.get("severity"),
                "message": limitation.get("message"),
                "scope": list(limitation.get("scope", [])),
            }
        )
    return triggers


def ledger_summary(entries: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """A compact, chronological view of the decision ledger."""

    rows: list[dict[str, object]] = []
    for entry in sorted(entries, key=lambda item: str(item.get("decided_at", ""))):
        rows.append(
            {
                "decision_id": entry.get("decision_id"),
                "study_id": entry.get("study_id"),
                "action": entry.get("action"),
                "decided_at": entry.get("decided_at"),
                "evidence_id": entry.get("evidence_id"),
                "evidence_as_of": entry.get("evidence_as_of"),
                "conclusion_grade": entry.get("conclusion_grade"),
                "supersedes": entry.get("supersedes", ""),
                "superseded_by": entry.get("superseded_by", ""),
                "review_triggers": sorted(
                    {str(item["code"]) for item in entry.get("review_triggers", [])}
                ),
            }
        )
    return rows
