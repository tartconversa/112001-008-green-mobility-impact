"""Tests for frozen evidence, the decision ledger, and input-change triggers."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from transport_eval.errors import IntegrityError, ValidationError
from transport_eval.workspace import StudyWorkspace, ledger_summary

from support import TempProject, read_csv, write_csv


def _acknowledge(workspace: StudyWorkspace, evidence_id: str) -> list[str]:
    snapshot = workspace.load_snapshot(evidence_id)
    return list(snapshot.evaluation["review_codes"])


class EvidenceTests(unittest.TestCase):
    def test_freeze_produces_a_stable_id_for_identical_inputs(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            first = workspace.freeze("PILOT", include_operational=False)
            second = workspace.freeze("PILOT", include_operational=False)
            self.assertEqual(first.evidence_id, second.evidence_id)
            self.assertEqual(first.digests, second.digests)

    def test_drift_is_detected_when_a_pinned_file_changes(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            path = project / "surveys_measures.csv"
            rows = read_csv(path)
            rows[0]["sample_n"] = str(int(rows[0]["sample_n"]) + 1)
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            self.assertEqual(workspace.verify_snapshot(snapshot.evidence_id), ("surveys_measures.csv",))

    def test_new_operational_material_is_reported_not_called_drift(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            operational = project / "operational"
            operational.mkdir(exist_ok=True)
            (operational / "trip_legs.csv").write_text(
                "journey_id,leg_no,mode,from_stop,to_stop,depart_at,person_group,sample_weight\n"
                "OP01,1,bus,A,B,2026-06-01T08:00,commuters,1.0\n",
                encoding="utf-8",
            )
            self.assertEqual(workspace.verify_snapshot(snapshot.evidence_id), ())
            self.assertEqual(workspace.new_inputs(snapshot.evidence_id), ("operational/trip_legs.csv",))

    def test_decision_is_blocked_when_pinned_input_changed(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            acknowledged = _acknowledge(workspace, snapshot.evidence_id)
            path = project / "network.csv"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                workspace.record_decision(
                    snapshot.evidence_id,
                    action="adjust",
                    rationale="test",
                    acknowledged_limitations=acknowledged,
                )


class DecisionLedgerTests(unittest.TestCase):
    def test_decision_requires_acknowledging_review_items(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            with self.assertRaises(ValidationError) as context:
                workspace.record_decision(snapshot.evidence_id, action="expand", rationale="expand now")
            self.assertIn("未被确认", str(context.exception))

    def test_decision_records_evidence_and_triggers(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            entry = workspace.record_decision(
                snapshot.evidence_id,
                action="adjust",
                rationale="继续试点并调整班次",
                acknowledged_limitations=_acknowledge(workspace, snapshot.evidence_id),
                decided_by="office",
                decided_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(entry["evidence_id"], snapshot.evidence_id)
            self.assertEqual(entry["action"], "adjust")
            self.assertTrue(entry["review_triggers"])
            codes = {item["code"] for item in entry["review_triggers"]}
            self.assertIn("COMPARISON_CORRIDOR_REMOVED", codes)
            stored = workspace.decisions()
            self.assertEqual(stored[0]["decision_id"], entry["decision_id"])

    def test_superseding_decision_links_both_ways(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            first = workspace.freeze("PILOT", include_operational=False)
            ack = _acknowledge(workspace, first.evidence_id)
            initial = workspace.record_decision(
                first.evidence_id,
                action="adjust",
                rationale="initial",
                acknowledged_limitations=ack,
                decided_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            later = workspace.record_decision(
                first.evidence_id,
                action="expand",
                rationale="later",
                acknowledged_limitations=ack,
                supersedes=initial["decision_id"],
                decided_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
            entries = {entry["decision_id"]: entry for entry in workspace.decisions()}
            self.assertEqual(entries[initial["decision_id"]]["superseded_by"], later["decision_id"])
            self.assertEqual(later["supersedes"], initial["decision_id"])

    def test_unknown_evidence_is_rejected(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            with self.assertRaises(ValidationError):
                workspace.record_decision("EV-nope", action="defer", rationale="x")

    def test_ledger_summary_is_chronological(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            ack = _acknowledge(workspace, snapshot.evidence_id)
            workspace.record_decision(
                snapshot.evidence_id,
                action="defer",
                rationale="later",
                acknowledged_limitations=ack,
                decided_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
            workspace.record_decision(
                snapshot.evidence_id,
                action="adjust",
                rationale="earlier",
                acknowledged_limitations=ack,
                decided_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            rows = ledger_summary(workspace.decisions())
            self.assertEqual([row["action"] for row in rows], ["adjust", "defer"])

    def test_post_decision_operational_data_enters_later_evidence_only(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            frozen = workspace.freeze("PILOT", include_operational=False)
            approved = frozen.evaluation
            operational = project / "operational"
            operational.mkdir(exist_ok=True)
            (operational / "trip_legs.csv").write_text(
                "journey_id,leg_no,mode,from_stop,to_stop,depart_at,person_group,sample_weight\n"
                "OP01,1,bus,A,B,2026-06-01T08:00,commuters,1.0\n"
                "OP02,1,bus,A,B,2026-06-02T08:00,commuters,1.0\n",
                encoding="utf-8",
            )
            later = workspace.evaluate("PILOT", include_operational=True)
            self.assertEqual(later.provenance["operational_records_used"], 2)
            # The frozen snapshot still shows the evidence the decision saw.
            reloaded = workspace.load_snapshot(frozen.evidence_id)
            self.assertEqual(reloaded.evaluation, approved)
            self.assertEqual(reloaded.include_operational, False)

    def test_compare_against_snapshot_explains_new_evidence(self):
        with TempProject() as project:
            workspace = StudyWorkspace(project)
            snapshot = workspace.freeze("PILOT", include_operational=False)
            operational = project / "operational"
            operational.mkdir(exist_ok=True)
            (operational / "trip_legs.csv").write_text(
                "journey_id,leg_no,mode,from_stop,to_stop,depart_at,person_group,sample_weight\n"
                "OP01,1,bus,A,B,2026-06-01T08:00,commuters,1.0\n",
                encoding="utf-8",
            )
            comparison = workspace.compare_with_snapshot(
                snapshot.evidence_id, include_operational=True
            )
            self.assertEqual(comparison["new_inputs_since_freeze"], ["operational/trip_legs.csv"])
            self.assertEqual(comparison["input_drift"], [])


if __name__ == "__main__":
    unittest.main()
