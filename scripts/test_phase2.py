"""Phase 2 fixture tests; never generate or modify Phase 1."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

import generate_phase2 as generator
import validate_phase2 as validator


class Phase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.config = json.loads(generator.CONFIG.read_text())
        generator.generate(cls.root, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_largest_remainder_conserves_counts_and_breaks_ties_by_id(self):
        self.assertEqual(generator.allocate(5, {'C': 1, 'B': 1, 'A': 1}), {'A': 2, 'B': 2, 'C': 1})
        self.assertEqual(sum(generator.allocate(100000, self.config['merchant_weights']).values()), 100000)

    def test_independent_sql_and_incident_contract(self):
        report, answers = validator.validate(self.root, write_expected=True)
        self.assertEqual(report['dataset_gate'], 'passed', report['errors'])
        self.assertEqual(report['analyst_gate'], 'pending')
        self.assertEqual(answers['variants']['baseline']['totals'][0]['attempts'], 100000)
        self.assertEqual(answers['variants']['incident']['totals'][0]['attempts'], 100000)
        self.assertGreater(answers['paired']['summary'][0]['converted_successes'], 0)
        self.assertEqual(answers['paired']['summary'][0]['changed_non_outcome_rows'], 0)

    def test_two_generations_have_identical_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            other = Path(folder)
            generator.generate(other, self.config)
            manifest = json.loads((self.root / 'evaluation/phase2/generation_manifest.json').read_text())
            for path in list(manifest['files']) + ['evaluation/phase2/generation_manifest.json',
                                                   'evaluation/phase2/incident_manifest.json']:
                self.assertEqual((self.root / path).read_bytes(), (other / path).read_bytes(), path)

    def test_amount_changes_do_not_change_traffic_or_outcomes(self):
        config = copy.deepcopy(self.config)
        config['amounts']['median_inr']['dining'] = 700
        with tempfile.TemporaryDirectory() as folder:
            other = Path(folder)
            generator.generate(other, config)
            base = validator.data_dir(self.root) / 'baseline/payments.csv'
            modified = validator.data_dir(other) / 'baseline/payments.csv'
            with base.open(newline='') as a, modified.open(newline='') as b:
                for original, changed in zip(csv.DictReader(a), csv.DictReader(b), strict=True):
                    original.pop('amount_paise')
                    changed.pop('amount_paise')
                    self.assertEqual(original, changed)

    def test_standardization_removes_exposure_mix_and_reports_missing_strata(self):
        rows = []
        # Same 90%/10% within-hour rates, reversed exposure shares across periods.
        for day, hour, n, successes in [('01', '12', 100, 90), ('01', '13', 10, 1),
                                       ('15', '12', 10, 9), ('15', '13', 100, 10), ('01', '03', 1, 1)]:
            for index in range(n):
                rows.append({'attempt_id': f'T{len(rows)}', 'attempted_at': f'2026-10-{day}T{hour}:00:00+05:30',
                             'merchant_id': 'M01', 'payer_bank_id': 'BANK_A', 'payment_method': 'UPI',
                             'amount_paise': '1000', 'currency': 'INR',
                             'status': 'SUCCESS' if index < successes else 'FAILED',
                             'failure_reason': '' if index < successes else 'BANK_TIMEOUT'})
        query = validator.queries(validator.EVALUATION / 'reference.sql')['standardized_periods']
        result = validator.sql_answers({'payments': rows}, {'standardized': query})['standardized'][0]
        self.assertEqual(result['baseline_standardized_pct'], 50)
        self.assertEqual(result['comparison_standardized_pct'], 50)
        self.assertEqual(result['change_pp'], 0)
        self.assertEqual(result['common_strata'], 2)
        self.assertEqual(result['excluded_baseline_attempts'], 1)
        self.assertEqual(result['excluded_comparison_attempts'], 0)

    def test_benchmark_answer_pointers_resolve(self):
        benchmark = validator.read_json(validator.EVALUATION / 'benchmark_questions.json')
        answers = validator.read_json(validator.EVALUATION / 'expected_answers.json')
        for question in benchmark['questions']:
            for pointer in question['answer_pointers']:
                value = answers
                for key in pointer.split('/')[1:]:
                    value = value[int(key)] if isinstance(value, list) else value[key]
                self.assertTrue(value, (question['id'], pointer))

    def test_modified_incident_record_is_rejected(self):
        path = validator.data_dir(self.root) / 'incident/payments.csv'
        original = path.read_bytes()
        try:
            with path.open(newline='') as stream:
                reader = csv.DictReader(stream)
                fields, rows = reader.fieldnames, list(reader)
            rows[0]['amount_paise'] = str(int(rows[0]['amount_paise']) + 1)
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fields, lineterminator='\n')
                writer.writeheader()
                writer.writerows(rows)
            report, _ = validator.validate(self.root, write_expected=True)
            self.assertEqual(report['dataset_gate'], 'failed')
            self.assertTrue(any('hash' in error or 'outcome' in error for error in report['errors']))
        finally:
            path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
