"""End-to-end CLI tests."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from support import ROOT, TempProject

CLI = [sys.executable, "-m", "transport_eval"]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class CliTests(unittest.TestCase):
    def test_evaluate_prints_markdown_report(self):
        result = run("--data", "examples/pilot", "evaluate", "--study", "PILOT")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# 绿色出行措施效果评估", result.stdout)
        self.assertIn("对照支持的变化", result.stdout)
        self.assertIn("无法解释的余量", result.stdout)

    def test_evaluate_json_is_machine_readable(self):
        result = run("--data", "examples/pilot", "evaluate", "--study", "PILOT", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["study_id"], "PILOT")
        self.assertIn("limitations", payload)
        self.assertEqual(payload["schema"], "transport-eval/evaluation-v1")

    def test_exclude_operational_flag_changes_the_evidence_label(self):
        result = run(
            "--data",
            "examples/pilot",
            "evaluate",
            "--study",
            "PILOT",
            "--exclude-operational",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["include_operational"])

    def test_full_freeze_decide_verify_flow(self):
        with TempProject() as project:
            workspace = str(project / "workspace")
            freeze = run(
                "--data", str(project), "--workspace", workspace,
                "freeze", "--study", "PILOT", "--exclude-operational",
            )
            self.assertEqual(freeze.returncode, 0, freeze.stderr)
            snapshot = json.loads(freeze.stdout)
            evidence_id = snapshot["evidence_id"]
            review = snapshot["review_codes"]

            decide = run(
                "--data", str(project), "--workspace", workspace,
                "decide",
                "--evidence", evidence_id,
                "--action", "adjust",
                "--rationale", "继续试点",
                *[item for code in review for item in ("--acknowledge", code)],
            )
            self.assertEqual(decide.returncode, 0, decide.stderr)

            verify = run(
                "--data", str(project), "--workspace", workspace, "verify",
                "--evidence", evidence_id,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["ok"])

            ledger = run("--data", str(project), "--workspace", workspace, "ledger")
            self.assertEqual(ledger.returncode, 0, ledger.stderr)
            rows = json.loads(ledger.stdout)
            self.assertEqual(rows[0]["action"], "adjust")

    def test_missing_input_exits_with_one(self):
        result = run("--data", "/tmp/does-not-exist", "evaluate")
        self.assertEqual(result.returncode, 1)

    def test_tampered_evidence_blocks_decision_with_exit_two(self):
        with TempProject() as project:
            workspace = str(project / "workspace")
            freeze = run(
                "--data", str(project), "--workspace", workspace,
                "freeze", "--study", "PILOT", "--exclude-operational",
            )
            evidence_id = json.loads(freeze.stdout)["evidence_id"]
            path = project / "periods.csv"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            decide = run(
                "--data", str(project), "--workspace", workspace,
                "decide",
                "--evidence", evidence_id,
                "--action", "expand",
                "--rationale", "force",
                "--acknowledge", "COMPARISON_CORRIDOR_REMOVED",
            )
            self.assertEqual(decide.returncode, 2)


if __name__ == "__main__":
    unittest.main()
