from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from app.config import Settings
from app.query.executor import connect


@pytest.mark.integration
def test_reciprocal_permissions_on_live_roles():
    settings = Settings.from_root()
    with psycopg.connect(host='127.0.0.1', port=settings.db_port, dbname='payments_analytics',
                         user='analyst_writer', password=Path('.local/analyst/writer_password').read_text().strip(),
                         autocommit=True) as writer, connect(settings) as reader:
        writer.execute('SET search_path=public,lifecycle_v1,analyst_meta,pg_catalog')
        assert writer.execute('SELECT generation,import_epoch FROM analyst_meta.control').fetchone()
        for fixture in ('scenario_a', 'scenario_b', 'scenario_a_dirty', 'phase2_baseline', 'phase2_incident', 'lifecycle_v1'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                writer.execute(sql.SQL('SELECT 1 FROM {}.payments LIMIT 0').format(sql.Identifier(fixture)))
        for table in ('control', 'checkpoint_migrations'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                writer.execute(sql.SQL('DELETE FROM analyst_meta.{} WHERE false').format(sql.Identifier(table)))
        assert not writer.execute("SELECT has_schema_privilege('analyst_meta','CREATE')").fetchone()[0]
        assert writer.execute("SELECT has_table_privilege('analyst_meta.checkpoints','INSERT')").fetchone()[0]
        reader.execute('SET default_transaction_read_only=off')
        reader.execute('SET search_path=analyst_meta,pg_catalog')
        for table in ('control', 'checkpoints'):
            relation = sql.Identifier('analyst_meta', table)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute(sql.SQL('SELECT 1 FROM {} LIMIT 0').format(relation))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute(sql.SQL('DELETE FROM {} WHERE false').format(relation))
