"""Independent hand calculations, lifecycle corruption and deterministic generation."""
import copy
from pathlib import Path
import tempfile
import unittest

import generate_phase3 as generator
import validate_phase3 as validator


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = validator.read_json(validator.EVALUATION/'hand_fixture.json')
        cls.config = validator.read_json(validator.CONFIG)

    def test_hand_calculated_recovery_and_pending_settlement(self):
        result = validator.sql_answers(self.fixture['tables'], self.fixture['parameters'])
        for section, expected in self.fixture['expected_checks'].items():
            for key, value in expected.items():
                self.assertEqual(result[section][0][key], value, f'{section}.{key}')
        # The recovering order contributes one paid order and two separate attempts.
        tables = copy.deepcopy(self.fixture['tables'])
        tables['orders'] = tables['orders'][:1]
        tables['payments'] = tables['payments'][:2]
        tables['settlements'] = tables['settlements'][:1]
        result = validator.sql_answers(tables,self.fixture['parameters'])
        self.assertEqual(result['orders'][0]['paid_orders_24h'],1)
        self.assertEqual(result['attempts'][0]['successes'],1)
        self.assertEqual(result['attempts'][0]['failures'],1)

    def test_temporal_join_does_not_match_neighbor_buckets(self):
        tables = copy.deepcopy(self.fixture['tables'])
        tables['bank_health'].append(dict(tables['bank_health'][0],observed_at='2026-10-28T10:10:00.000+05:30'))
        result = validator.sql_answers(tables,self.fixture['parameters'])
        self.assertEqual(result['temporal_join'][0],{'joined_rows':4,'distinct_attempts':4,'unmatched_attempts':0})

    def test_maturity_cutoff_is_inclusive(self):
        params = dict(self.fixture['parameters'],cutoff='2026-10-29T10:00:00.000+05:30')
        result = validator.sql_answers(self.fixture['tables'],params)
        self.assertEqual(result['orders'][0]['eligible_orders'],2)
        self.assertEqual(result['orders'][0]['paid_orders_24h'],1)
        self.assertEqual(result['settlements'][0]['due_attempts'],0)
        self.assertIsNone(result['settlements'][0]['completion_pct'])

    def test_conversion_24h_boundary_and_attempt_window_are_distinct(self):
        tables = copy.deepcopy(self.fixture['tables'])
        tables['orders'] = tables['orders'][:1]
        tables['payments'] = tables['payments'][:2]
        tables['settlements'] = tables['settlements'][:1]
        params = dict(self.fixture['parameters'],cutoff='2026-11-01T00:00:00.000+05:30')
        retry = tables['payments'][1]
        retry['attempted_at'] = '2026-10-29T09:59:59.000+05:30'
        for millisecond, paid in (('000',1),('001',0)):
            with self.subTest(millisecond=millisecond):
                retry['completed_at'] = f'2026-10-29T10:00:00.{millisecond}+05:30'
                result = validator.sql_answers(tables,params)
                self.assertEqual(result['orders'][0]['paid_orders_24h'],paid)
                self.assertEqual(result['orders'][0]['paid_orders_by_cutoff'],1)
                self.assertEqual(result['attempts'][0]['attempts'],1)
                self.assertEqual(result['attempts'][0]['successes'],0)

    def test_benchmark_answers_resolve(self):
        benchmark = validator.read_json(validator.EVALUATION/'benchmark_questions.json')
        answers = validator.read_json(validator.EVALUATION/'expected_answers.json')
        for question in benchmark['questions']:
            value = answers
            for component in question['answer_pointer'].strip('/').split('/'):
                value = value[int(component)] if isinstance(value,list) else value[component]
            self.assertIsNotNone(value)

    def test_lifecycle_validator_rejects_corruption(self):
        config = dict(self.config,observation_cutoff=self.fixture['parameters']['cutoff'])
        self.assertEqual(validator.check_quality(self.fixture['tables'],config),{})
        cases = [('payments',1,'attempt_number','3','consecutive attempts'),
                 ('payments',1,'amount_paise','10001','attempt order attributes'),
                 ('payments',0,'status','SUCCESS','multiple successes'),
                 ('payments',1,'attempted_at','2026-10-28T10:04:02.000+05:30','retry delay'),
                 ('settlements',0,'attempt_id','L000000001','settlement on failure'),
                 ('settlements',1,'settlement_status','SETTLED','baseline settlement state'),
                 ('bank_health',0,'observed_at','2026-10-28T09:05:00.000+05:30','unmatched bank health')]
        for table,index,field,value,label in cases:
            with self.subTest(label=label):
                tables = copy.deepcopy(self.fixture['tables'])
                tables[table][index][field] = value
                self.assertIn(label,validator.check_quality(tables,config))

    def test_retry_cap_and_named_stream_independence(self):
        config = copy.deepcopy(self.config)
        config.update(orders=200,retry_probability=1)
        config['success_probability'] = {method:{bank:0 for bank in config['bank_weights']} for method in ('CARD','UPI')}
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = generator.generate(Path(first),config)
            self.assertEqual(len(a['payments']),600)
            self.assertEqual(a['settlements'],[])
            self.assertEqual(validator.check_quality(a,config),{})
            generator.generate(Path(second),config)
            for name in generator.FIELDS:
                self.assertEqual((generator.data_dir(Path(first))/f'{name}.csv').read_bytes(),
                                 (generator.data_dir(Path(second))/f'{name}.csv').read_bytes())
            config['bank_health']['availability_min_pct'] = 98
            b = generator.generate(Path(second),config)
            self.assertEqual(a['payments'],b['payments'])
            self.assertNotEqual(a['bank_health'],b['bank_health'])


if __name__ == '__main__':
    unittest.main()
