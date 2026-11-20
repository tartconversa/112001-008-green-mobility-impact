"""Estimator tests for journey counting, DID decomposition, and signals."""

from __future__ import annotations

import unittest
from decimal import Decimal

from transport_eval import evaluate, load_workspace

from support import DATA, PILOT


class JourneyUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = load_workspace(PILOT)
        cls.evaluation = evaluate(cls.inputs, "PILOT", include_operational=False)

    def test_multi_leg_journeys_are_counted_once(self):
        total_legs = sum(journey.leg_count for journey in self.inputs.journeys.values())
        total_journeys = len(self.inputs.journeys)
        self.assertGreater(total_legs, total_journeys)
        counted = sum(observation.journeys for observation in self.evaluation.observations)
        self.assertLessEqual(counted, total_journeys)

    def test_observation_rows_never_use_leg_counts_as_people(self):
        for observation in self.evaluation.observations:
            self.assertLessEqual(observation.journeys, len(self.inputs.journeys))

    def test_treated_rate_rises_while_comparison_stays_flat(self):
        by_key = {(o.corridor_id, o.period_id): o for o in self.evaluation.observations}
        treated_pre = by_key[("RIV", "2025-Q4")].rate_per_1000
        treated_post = by_key[("RIV", "2026-Q2")].rate_per_1000
        comparison_pre = by_key[("DOC", "2025-Q4")].rate_per_1000
        comparison_post = by_key[("DOC", "2026-Q2")].rate_per_1000
        self.assertGreater(treated_post, treated_pre)
        self.assertLess(abs(comparison_post - comparison_pre), treated_post - treated_pre)

    def test_decomposition_adds_up(self):
        primary = self.evaluation.effects[0]
        self.assertIsNotNone(primary.did)
        rebuilt = primary.did + primary.unexplained
        self.assertEqual(rebuilt, primary.treated_change.absolute)

    def test_comparison_supported_change_has_confidence_interval(self):
        primary = self.evaluation.effects[0]
        self.assertIsNotNone(primary.ci_low)
        self.assertIsNotNone(primary.ci_high)
        self.assertLess(primary.ci_low, primary.ci_high)

    def test_counter_cross_check_direction_agrees(self):
        primary = self.evaluation.effects[0]
        counter = self.evaluation.effects[1]
        self.assertEqual(counter.metric, "counter_relative_change")
        self.assertEqual(primary.did is not None and primary.did > 0, counter.did > 0)

    def test_contaminated_comparison_is_removed_not_used(self):
        self.assertIn("HIL", self.evaluation.comparability["comparison_corridors"])
        self.assertNotIn("HIL", self.evaluation.comparison_corridors)
        self.assertIn("DOC", self.evaluation.comparison_corridors)
        removed = {item["corridor_id"] for item in self.evaluation.comparability["removed_corridors"]}
        self.assertEqual(removed, {"HIL"})

    def test_removed_comparison_forces_review(self):
        self.assertTrue(self.evaluation.review_codes)
        self.assertIn("COMPARISON_CORRIDOR_REMOVED", self.evaluation.review_codes)

    def test_review_required_limits_expansion(self):
        self.assertNotEqual(self.evaluation.recommendation["direction"], "expand_candidate")

    def test_operational_exclusion_keeps_the_estimate_identical(self):
        operational_excluded = evaluate(self.inputs, "PILOT", include_operational=False)
        operational_included = evaluate(self.inputs, "PILOT", include_operational=True)
        self.assertEqual(
            operational_excluded.as_dict()["effects"],
            operational_included.as_dict()["effects"],
        )
        self.assertEqual(operational_included.provenance["operational_records_used"], 0)

    def test_sensitivity_variants_are_reported(self):
        variants = {item["variant"] for item in self.evaluation.sensitivity}
        self.assertIn("exclude_off_version", variants)
        self.assertIn("exclude_relocated", variants)
        self.assertIn("base_survey_denominator", variants)
        self.assertIn("pin_stops_to_pre_period", variants)


class RootFixtureTests(unittest.TestCase):
    def test_root_fixture_evaluates_without_crashing(self):
        evaluation = evaluate(load_workspace(DATA), "ST1")
        self.assertIsNotNone(evaluation.effects)
        self.assertIn(evaluation.conclusion_grade, {"supported", "conditional", "insufficient"})

    def test_single_journey_with_two_legs_contributes_one_unit(self):
        # Only J01 lies inside the study window and in a study corridor.
        inputs = load_workspace(DATA)
        journey = inputs.journeys["J01"]
        self.assertEqual(journey.leg_count, 2)
        evaluation = evaluate(inputs, "ST1")
        by_key = {(o.corridor_id, o.period_id): o.journeys for o in evaluation.observations}
        # The two-leg journey is one unit in North; the comparison corridor's
        # bike journey (J02) is one unit in West, not a share of J01's legs.
        self.assertEqual(by_key[("North", "2026-Q2")], 1)
        self.assertEqual(by_key[("West", "2026-Q2")], 1)
        total = sum(observation.journeys for observation in evaluation.observations)
        self.assertEqual(total, 2)


class RatioGuardTests(unittest.TestCase):
    def test_decimal_ratio_is_exact(self):
        value = Decimal("3") / Decimal("4") * Decimal("1000")
        self.assertEqual(value, Decimal("750"))


if __name__ == "__main__":
    unittest.main()
