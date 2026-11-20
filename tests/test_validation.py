"""Validation tests: malformed input must fail loudly and name the field."""

from __future__ import annotations

import unittest
from pathlib import Path

from transport_eval import load_workspace
from transport_eval.errors import InputError, ValidationError

from support import PILOT, TempProject, read_csv, write_csv


class ValidationTests(unittest.TestCase):
    def test_missing_required_file_is_an_input_error(self):
        with TempProject() as project:
            (project / "trip_legs.csv").unlink()
            with self.assertRaises(InputError):
                load_workspace(project)

    def test_missing_column_names_the_file(self):
        with TempProject() as project:
            path = project / "surveys_measures.csv"
            rows = read_csv(path)
            for row in rows:
                row.pop("sample_n")
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            with self.assertRaises(ValidationError) as context:
                load_workspace(project)
            self.assertIn("sample_n", str(context.exception))

    def test_unknown_measure_identifier_is_rejected(self):
        with TempProject() as project:
            path = project / "study_windows.csv"
            rows = read_csv(path)
            rows[-1]["measure_id"] = "M99"
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            with self.assertRaises(ValidationError):
                load_workspace(project)

    def test_inconsistent_group_within_journey_is_rejected(self):
        with TempProject() as project:
            path = project / "trip_legs.csv"
            rows = read_csv(path)
            transfer = [row for row in rows if row["journey_id"] == rows[0]["journey_id"]]
            if len(transfer) < 2:
                self.skipTest("fixture has no multi-leg journey")
            transfer[1]["person_group"] = "students"
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            with self.assertRaises(ValidationError) as context:
                load_workspace(project)
            self.assertIn("人群标签", str(context.exception))

    def test_operational_file_cannot_overwrite_a_frozen_journey(self):
        with TempProject() as project:
            operational = project / "operational"
            operational.mkdir(exist_ok=True)
            existing = read_csv(project / "trip_legs.csv")[0]
            write_csv(
                operational / "trip_legs.csv",
                [list(existing.keys()), list(existing.values())],
            )
            with self.assertRaises(ValidationError) as context:
                load_workspace(project)
            self.assertIn("不得覆盖冻结输入", str(context.exception))

    def test_amendment_with_stale_previous_values_is_rejected(self):
        with TempProject() as project:
            path = project / "survey_amendments.csv"
            rows = read_csv(path)
            rows[0]["previous_sample_n"] = "999"
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            with self.assertRaises(ValidationError) as context:
                load_workspace(project)
            self.assertIn("previous_sample_n", str(context.exception))

    def test_window_requires_a_known_period(self):
        with TempProject() as project:
            path = project / "study_windows.csv"
            rows = read_csv(path)
            rows[0]["period_id"] = "2030-Q1"
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            with self.assertRaises(ValidationError):
                load_workspace(project)

    def test_duplicate_ids_are_rejected(self):
        with TempProject() as project:
            path = project / "corridors.csv"
            rows = read_csv(path)
            rows.append(dict(rows[0]))
            write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])
            with self.assertRaises(ValidationError) as context:
                load_workspace(project)
            self.assertIn("重复", str(context.exception))

    def test_pilot_fixture_itself_is_valid(self):
        inputs = load_workspace(PILOT)
        self.assertTrue(inputs.journeys)


if __name__ == "__main__":
    unittest.main()
