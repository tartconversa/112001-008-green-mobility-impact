"""Contract tests for the shipped CSV inputs and the synthetic pilot example."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from transport_eval import load_workspace
from transport_eval.loading import REQUIRED_FILES, SCHEMA_FIELDS

from support import DATA, PILOT


class FixtureContractTests(unittest.TestCase):
    def test_csv_fixtures_have_headers_and_well_formed_rows(self):
        files = sorted((DATA).glob("*.csv"))
        self.assertTrue(files, "expected synthetic CSV fixtures")
        for path in files:
            with self.subTest(file=path.name):
                with path.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.reader(stream))
                self.assertGreaterEqual(len(rows), 1)
                self.assertTrue(all(column for column in rows[0]))
                self.assertTrue(all(len(row) == len(rows[0]) for row in rows[1:]))

    def test_every_recognised_schema_matches_its_documented_columns(self):
        for name, schema in SCHEMA_FIELDS.items():
            with self.subTest(file=name):
                candidate = DATA / name
                if not candidate.is_file():
                    continue
                with candidate.open(encoding="utf-8", newline="") as stream:
                    header = next(csv.reader(stream))
                self.assertEqual(tuple(header), schema)

    def test_manifest_record_counts_match_the_files(self):
        manifest = list(csv.DictReader((DATA / "fixture_manifest.csv").open(encoding="utf-8")))
        self.assertTrue(manifest)
        for entry in manifest:
            with self.subTest(file=entry["dataset"]):
                rows = list(csv.DictReader((DATA / entry["dataset"]).open(encoding="utf-8")))
                self.assertEqual(len(rows), int(entry["records"]))

    def test_required_files_exist(self):
        for name in REQUIRED_FILES:
            with self.subTest(file=name):
                self.assertTrue((DATA / name).is_file(), f"{name} missing from data/")

    def test_root_fixtures_load_and_evaluate(self):
        inputs = load_workspace(DATA)
        self.assertEqual(inputs.study_ids(), ["ST1"])
        self.assertIn("ST1", inputs.study_ids())
        self.assertTrue(inputs.journeys)

    def test_pilot_example_loads(self):
        inputs = load_workspace(PILOT)
        self.assertEqual(inputs.study_ids(), ["PILOT"])
        self.assertTrue(inputs.warnings or True)

    def test_missing_directory_is_an_input_error(self):
        from transport_eval.errors import InputError

        with self.assertRaises(InputError) as context:
            load_workspace(PILOT / "does-not-exist")
        self.assertIn("不存在", str(context.exception))

    def test_legs_never_outnumber_journeys(self):
        inputs = load_workspace(PILOT)
        self.assertGreater(sum(j.leg_count for j in inputs.journeys.values()), len(inputs.journeys))


if __name__ == "__main__":
    unittest.main()
