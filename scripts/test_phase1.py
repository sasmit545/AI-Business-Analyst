"""End-to-end acceptance and corruption checks using only the standard library."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent


class Phase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.run_script("generate_phase1.py", "--output-root", str(cls.root))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def run_script(name, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPTS / name), *args],
                                capture_output=True, text=True)
        if result.returncode != expected:
            raise AssertionError(f"exit {result.returncode}, expected {expected}: {result.stdout}\n{result.stderr}")
        return result

    def test_full_acceptance_and_reproducibility(self):
        self.run_script("validate_phase1.py", "--root", str(self.root),
                        "--write-expected", "--check-reproducibility")
        report = json.loads((self.root / "evaluation/phase1/validation_report.json").read_text())
        self.assertEqual(report["dataset_gate"], "passed")
        self.assertEqual(report["analyst_gate"], "pending")
        self.assertTrue(report["reproducibility"]["identical"])

    def test_dirty_analysis_is_blocked(self):
        result = self.run_script("validate_phase1.py", "--analyze",
                                 str(self.root / "data/synthetic/phase1/scenario_a_dirty"), expected=1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["analysis_status"], "blocked")
        self.assertEqual(payload["quality"]["duplicate_occurrences"], 20)
        self.assertEqual(payload["quality"]["missing_timestamps"], 10)
        self.assertEqual(payload["quality"]["orphan_merchants"], 10)
        self.assertNotIn("metrics", payload)

    def test_invalid_values_block_analysis(self):
        import shutil
        cases = [("amount_paise", "0", "invalid_amounts"),
                 ("amount_paise", "1.5", "invalid_amounts"),
                 ("status", "PENDING", "invalid_outcomes"),
                 ("attempted_at", "2026-10-01T12:00:00Z", "invalid_timestamps"),
                 ("payer_bank_id", "BANK_Z", "orphan_banks"),
                 ("failure_reason", "INVALID", "invalid_outcomes")]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scenario"
            shutil.copytree(self.root / "data/synthetic/phase1/scenario_a", target)
            path = target / "payments.csv"
            original = path.read_bytes()
            for field, value, error in cases:
                with self.subTest(field=field, value=value):
                    path.write_bytes(original)
                    with path.open(newline="", encoding="utf-8") as stream:
                        reader = csv.DictReader(stream)
                        fields, rows = reader.fieldnames, list(reader)
                    rows[0][field] = value
                    with path.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(stream, fields, lineterminator="\n")
                        writer.writeheader()
                        writer.writerows(rows)
                    result = self.run_script("validate_phase1.py", "--analyze", str(target), expected=1)
                    payload = json.loads(result.stdout)
                    self.assertGreater(payload["quality"][error], 0)
                    self.assertNotIn("metrics", payload)

    def test_changed_file_fails_manifest_check(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(self.root / "data", root / "data")
            shutil.copytree(self.root / "evaluation", root / "evaluation")
            path = root / "data/synthetic/phase1/scenario_a/payments.csv"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace(",INR,", ",USD,", 1), encoding="utf-8", newline="")
            result = self.run_script("validate_phase1.py", "--root", str(root), expected=1)
            report = json.loads((root / "evaluation/phase1/validation_report.json").read_text())
            self.assertEqual(report["dataset_gate"], "failed")
            self.assertTrue(any("hash" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
