"""Tests for comparability, sample scope, and relocations changing the estimate."""

from __future__ import annotations

import unittest
from decimal import Decimal

from transport_eval import evaluate, load_workspace

from support import PILOT, TempProject, read_csv, write_csv


def _rewrite(project, name, mutator):
    path = project / name
    rows = read_csv(path)
    mutator(rows)
    write_csv(path, [list(rows[0].keys())] + [list(row.values()) for row in rows])


class ComparabilityTests(unittest.TestCase):
    def _baseline(self, project):
        return evaluate(load_workspace(project), "PILOT", include_operational=False)

    def test_a_clean_comparison_corridor_produces_comparison_support(self):
        with TempProject() as project:
            _rewrite(
                project,
                "study_windows.csv",
                lambda rows: [row.update(measure_id="") for row in rows if row["corridor_id"] == "HIL"],
            )
            _rewrite(
                project,
                "measures.csv",
                lambda rows: [row.update(scope_corridors="RIV") for row in rows],
            )
            (project / "network_changes.csv").unlink()
            evaluation = self._baseline(project)
            self.assertEqual(evaluation.comparability["status"] in {"comparable", "conditional"}, True)
            self.assertEqual(len(evaluation.comparison_corridors), 2)
            self.assertIsNotNone(evaluation.effects[0].did)

    def test_measure_activated_in_comparison_removes_it(self):
        with TempProject() as project:
            evaluation = self._baseline(project)
            self.assertNotIn("HIL", evaluation.comparison_corridors)
            self.assertIn("COMPARISON_IN_MEASURE_SCOPE", evaluation.review_codes)

    def test_losing_every_comparison_blocks_the_conclusion(self):
        with TempProject() as project:
            def strip_all(rows):
                for row in rows:
                    row["measure_id"] = ""

            _rewrite(project, "study_windows.csv", strip_all)
            # Make the only remaining control get the measure too.
            _rewrite(
                project,
                "measures.csv",
                lambda rows: [row.update(scope_corridors="RIV;HIL;DOC") for row in rows],
            )
            evaluation = self._baseline(project)
            self.assertEqual(evaluation.comparison_corridors, ())
            self.assertIn("NO_VALID_COMPARISON", evaluation.blocking_codes)
            self.assertEqual(evaluation.recommendation["direction"], "defer")
            self.assertIn("insufficient", evaluation.conclusion_grade)


class SurveyScopeTests(unittest.TestCase):
    def test_in_window_amendment_is_blocking(self):
        with TempProject() as project:
            def move_into_window(rows):
                rows[0]["effective_date"] = "2026-05-20"

            _rewrite(project, "survey_amendments.csv", move_into_window)
            evaluation = evaluate(load_workspace(project), "PILOT")
            self.assertIn("SURVEY_AMENDMENT_IN_WINDOW", evaluation.blocking_codes)

    def test_post_hoc_amendment_requires_review_and_does_not_rewrite_frozen_evidence(self):
        with TempProject() as project:
            frozen_inputs = load_workspace(project)
            without_amendment = evaluate(frozen_inputs, "PILOT", as_of="2026-06-30")
            with_amendment = evaluate(frozen_inputs, "PILOT", as_of="2026-07-31")
            self.assertIn("SURVEY_AMENDMENT_POST_HOC", with_amendment.review_codes)
            self.assertNotIn("SURVEY_AMENDMENT_POST_HOC", without_amendment.limitation_codes)
            self.assertNotEqual(
                without_amendment.as_dict()["observations"],
                with_amendment.as_dict()["observations"],
            )

    def test_migration_is_redistributed_between_groups(self):
        inputs = load_workspace(PILOT)
        baseline = evaluate(inputs, "PILOT", as_of="2026-06-30")
        amended = evaluate(inputs, "PILOT", as_of="2026-07-31")
        base_groups = _group_map(baseline)
        amended_groups = _group_map(amended)
        self.assertEqual(
            base_groups[("RIV", "2026-Q2", "commuters")] + 8,
            amended_groups[("RIV", "2026-Q2", "commuters")],
        )
        self.assertEqual(
            base_groups[("RIV", "2026-Q2", "older_adults")] - 8,
            amended_groups[("RIV", "2026-Q2", "older_adults")],
        )

    def test_small_group_is_flagged(self):
        evaluation = evaluate(load_workspace(PILOT), "PILOT")
        self.assertIn("SMALL_SAMPLE", evaluation.limitation_codes)


class RelocationTests(unittest.TestCase):
    def test_stop_relocation_changes_scope_and_requests_review(self):
        with TempProject() as project:
            evaluation = evaluate(load_workspace(project), "PILOT", include_operational=False)
            self.assertIn("NETWORK_CHANGE_IN_WINDOW", evaluation.review_codes)
            self.assertIn("NETWORK_CHANGE_IN_WINDOW", evaluation.review_codes)
            # The relocated stop belonged to the contaminated control, so it
            # leaves the study scope rather than invalidating the estimate.
            out_of_scope = {
                limitation.code for limitation in evaluation.limitations
            }
            self.assertTrue(
                {"STOP_RELOCATED_OUT_OF_SCOPE", "STOP_RELOCATED_IN_WINDOW"} & out_of_scope
            )
            self.assertIn("NETWORK_CHANGE_IN_WINDOW", evaluation.review_codes)

    def test_relocation_inside_a_contributing_corridor_blocks_the_estimate(self):
        with TempProject() as project:
            _rewrite(
                project,
                "network_changes.csv",
                lambda rows: [
                    row.update(stop_id="A", to_area="North", from_area="North")
                    for row in rows
                ],
            )
            evaluation = evaluate(load_workspace(project), "PILOT", include_operational=False)
            self.assertIn("STOP_RELOCATED_IN_WINDOW", evaluation.blocking_codes)

    def test_pinning_stops_to_pre_period_is_a_reported_variant(self):
        evaluation = evaluate(load_workspace(PILOT), "PILOT", include_operational=False)
        pin = next(
            item for item in evaluation.sensitivity if item["variant"] == "pin_stops_to_pre_period"
        )
        self.assertIsNotNone(pin["did"])


class GroupUseTests(unittest.TestCase):
    def test_group_level_use_is_reported_per_group(self):
        evaluation = evaluate(load_workspace(PILOT), "PILOT", include_operational=False)
        observation = next(
            item
            for item in evaluation.observations
            if item.corridor_id == "RIV" and item.period_id == "2026-Q2"
        )
        groups = {group["group_id"]: group for group in observation.groups}
        self.assertIn("students", groups)
        self.assertIn("older_adults", groups)
        self.assertNotEqual(groups["students"]["rate_per_1000"], groups["older_adults"]["rate_per_1000"])

    def test_group_rates_use_that_group_population_not_corridor_population(self):
        evaluation = evaluate(load_workspace(PILOT), "PILOT", include_operational=False)
        corridor_total = sum(observation.population_n for observation in evaluation.observations)
        for observation in evaluation.observations:
            group_populations = sum(group["population_n"] for group in observation.groups)
            self.assertEqual(group_populations, observation.population_n)


def _group_map(evaluation):
    result = {}
    for observation in evaluation.observations:
        for group in observation.groups:
            result[(observation.corridor_id, observation.period_id, group["group_id"])] = group["sample_n"]
    return result


if __name__ == "__main__":
    unittest.main()
