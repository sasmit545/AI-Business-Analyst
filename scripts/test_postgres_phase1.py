"""Offline checks use existing fixtures only; live tests require native PostgreSQL."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

import postgres_phase1 as pg


class OfflineTests(unittest.TestCase):
    def test_start_reuses_connected_server_without_process_probe(self):
        with patch.object(pg, 'require_native'), patch.object(pg, 'init_secrets'), \
             patch.object(pg, 'PGDATA') as data, patch.object(pg, 'save_json'), \
             patch.object(pg, 'psql', return_value=Mock(returncode=0)), \
             patch.object(pg, 'check_server_identity') as identity, patch.object(pg, 'run_native') as native:
            (data / 'PG_VERSION').is_file.return_value = True
            pg.start_server()
            identity.assert_called_once()
            native.assert_not_called()

    def test_existing_sources_and_ground_truths(self):
        before = pg.fixture_hashes()
        pg.verify_sources()
        self.assertEqual(pg.fixture_hashes(), before)

    def test_only_known_scenarios_can_enter_sql(self):
        for invalid in ('public', 'scenario_a; DROP DATABASE postgres', '', 'SCENARIO_A'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                pg.require_scenario(invalid)

    def test_ingestion_preserves_empty_fields_and_is_atomic(self):
        statement = pg.ingestion_sql()
        self.assertTrue(statement.startswith('BEGIN;'))
        self.assertTrue(statement.rstrip().endswith('COMMIT;'))
        self.assertEqual(statement.count('COPY '), 23)
        self.assertEqual(statement.count('HEADER MATCH'), 23)
        self.assertEqual(statement.count('FORCE_NOT_NULL'), 23)
        self.assertNotIn('CASCADE', statement)
        self.assertNotIn('evaluation/', statement)
        self.assertNotIn('ON CONFLICT', statement)

    def test_postgres_queries_cover_saved_answer_sections(self):
        expected = pg.read_json(pg.EVALUATION / 'expected_answers.json')
        self.assertEqual(set(pg.reference_queries()), set(expected['scenarios']['scenario_a']))
        phase2_expected = pg.read_json(pg.phase2.EVALUATION / 'expected_answers.json')
        for schema, variant in pg.PHASE2_SCENARIOS.items():
            self.assertEqual(set(pg.reference_queries(schema)), set(phase2_expected['variants'][variant]))
        self.assertEqual(set(pg.phase2.queries(pg.ROOT / 'database/phase2/paired_reference.sql')), set(phase2_expected['paired']))
        self.assertEqual(set(pg.reference_queries('lifecycle_v1')),
                         set(pg.read_json(pg.phase3.EVALUATION / 'expected_answers.json')['metrics']))

    def test_role_selection_revokes_every_other_scenario(self):
        for selected in pg.SCENARIOS:
            statement = pg.selection_sql(selected)
            self.assertIn(f'GRANT USAGE ON SCHEMA {selected} TO ai_analyst', statement)
            for schema in pg.SCENARIOS:
                self.assertIn(f'REVOKE ALL ON SCHEMA {schema} FROM ai_analyst', statement)
            self.assertNotIn('WITH GRANT OPTION', statement)

    def test_selection_fences_previous_generation_before_reopening_login(self):
        sql = pg.selection_sql('scenario_a')
        self.assertLess(sql.index('generation = generation + 1'), sql.index('pg_terminate_backend'))
        self.assertLess(sql.index("scenario = 'scenario_a', ready = true"), sql.index('ALTER ROLE ai_analyst LOGIN'))

    def test_import_fences_old_epoch_before_copy_and_restores_after_last_copy(self):
        sql = pg.ingestion_sql()
        self.assertLess(sql.index('import_epoch = import_epoch + 1'), sql.index('TRUNCATE TABLE'))
        self.assertLess(sql.rindex('COPY '), sql.index('SET ready = true'))

    def test_native_import_reads_only_the_twenty_three_csvs(self):
        statement = pg.ingestion_sql()
        for scenario in pg.SCENARIOS:
            for table in pg.tables_for(scenario):
                self.assertIn(pg.sql_literal(pg.data_path(scenario) / f'{table}.csv'), statement)
        self.assertNotIn(pg.EVALUATION.as_posix(), statement)
        self.assertNotIn(pg.LOCAL.as_posix(), statement)

    def test_install_archive_cannot_escape_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'unsafe.zip'
            destination = Path(folder) / 'runtime'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../escaped.txt', 'must not be written')
            with self.assertRaises(ValueError):
                pg.extract_binaries(archive, destination)
            self.assertFalse((Path(folder) / 'escaped.txt').exists())


@unittest.skipUnless(os.environ.get('PAYMENTS_POSTGRES_INTEGRATION') == '1',
                     'Live PostgreSQL tests not requested; run postgres_phase1.py test')
class PostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg.require_native()
        pg.check_server_identity()
        cls.original = pg.selected_scenario()

    @classmethod
    def tearDownClass(cls):
        pg.select_scenario(cls.original)

    def test_imported_data_and_sql_ground_truths(self):
        report = pg.validate_database()
        self.assertEqual(report['status'], 'passed')

    def test_repeat_ingestion_preserves_all_rows(self):
        before = pg.database_row_hashes()
        pg.ingest()
        self.assertEqual(pg.database_row_hashes(), before)

    def test_permissions_for_each_selected_scenario(self):
        for scenario in pg.SCENARIOS:
            with self.subTest(scenario=scenario):
                pg.select_scenario(scenario)
                pg.check_permissions(scenario)

    def test_failed_import_rolls_back(self):
        before = pg.database_row_hashes()
        statement = pg.ingestion_sql().replace(
            pg.sql_literal(pg.DATA / 'scenario_b/payments.csv'), pg.sql_literal(pg.LOCAL / 'nonexistent.csv'))
        result = pg.psql(statement, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('58P01', result.stderr)
        self.assertEqual(pg.database_row_hashes(), before)

    def test_lifecycle_hand_fixture_sql(self):
        fixture = pg.read_json(pg.phase3.EVALUATION / 'hand_fixture.json')
        statements = ['BEGIN;', 'SET LOCAL search_path = pg_temp, pg_catalog;']
        for table, fields in pg.phase3.FIELDS.items():
            statements.append(f'CREATE TEMP TABLE {table} (' + ', '.join(field+' text' for field in fields) + ') ON COMMIT DROP;')
            for row in fixture['tables'][table]:
                statements.append(f'INSERT INTO {table} VALUES (' + ','.join(pg.sql_literal(row[f]) for f in fields) + ');')
        for query in pg.reference_queries('lifecycle_v1', fixture['parameters']).values():
            statements.append("SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) FROM ("+query+') r;')
        statements.append('ROLLBACK;')
        import json
        observed = [json.loads(line) for line in pg.psql('\n'.join(statements)).stdout.splitlines() if line.strip()]
        expected = pg.phase3.sql_answers(fixture['tables'],fixture['parameters'])
        self.assertEqual(observed,list(expected.values()))

    def test_clean_constraints_reject_corruption(self):
        checks = [
            ('23505', 'INSERT INTO scenario_a.payments SELECT * FROM scenario_a.payments LIMIT 1'),
            ('23503', "UPDATE scenario_a.payments SET merchant_id = 'M_ORPHAN' WHERE attempt_id = 'A000001'"),
            ('23514', "UPDATE scenario_a.payments SET amount_paise = '-1' WHERE attempt_id = 'A000001'"),
            ('23514', "UPDATE scenario_a.payments SET status = 'PENDING' WHERE attempt_id = 'A000001'"),
            ('23505', 'INSERT INTO phase2_baseline.payments SELECT * FROM phase2_baseline.payments LIMIT 1'),
            ('23503', "UPDATE phase2_incident.payments SET merchant_id = 'M_ORPHAN' WHERE attempt_id = 'R00000001'"),
            ('23514', "UPDATE phase2_baseline.payments SET amount_paise = '999' WHERE attempt_id = 'R00000001'"),
            ('23514', "UPDATE phase2_incident.payments SET failure_reason = 'UNKNOWN' WHERE attempt_id = 'R00000001'"),
            ('23505', 'INSERT INTO lifecycle_v1.payments SELECT * FROM lifecycle_v1.payments LIMIT 1'),
            ('23503', "UPDATE lifecycle_v1.payments SET order_id = 'O999999999' WHERE attempt_id = 'L000000001'"),
            ('23514', "UPDATE lifecycle_v1.payments SET processing_duration_ms = '0' WHERE attempt_id = 'L000000001'"),
            ('23503', "UPDATE lifecycle_v1.settlements SET gross_amount_paise = '1' WHERE settlement_id = (SELECT min(settlement_id) FROM lifecycle_v1.settlements)"),
            ('23514', "UPDATE lifecycle_v1.bank_health SET availability_pct = '101' WHERE bank_id='BANK_A'"),
        ]
        for code, statement in checks:
            with self.subTest(statement=statement):
                result = pg.psql(f'BEGIN; {statement}; ROLLBACK;', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(code, result.stderr)


if __name__ == '__main__':
    unittest.main()
