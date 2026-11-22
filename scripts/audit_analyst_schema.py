"""Developer-only read-only audit and dependency smoke; never a model tool."""
import hashlib
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.context.catalog import catalog
from app.quality.checks import check_quality
from app.query.executor import Authorization, Budget, Bundle


def main():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langgraph.graph import StateGraph, START, END
    import plotly.graph_objects as go
    import streamlit
    from typing import TypedDict

    class State(TypedDict):
        value: int

    graph = StateGraph(State)
    graph.add_node('increment', lambda state: {'value': state['value']+1})
    graph.add_edge(START, 'increment')
    graph.add_edge('increment', END)
    assert graph.compile().invoke({'value': 1})['value'] == 2
    api = FastAPI()
    @api.get('/health')
    def health():
        return {'ok': True}
    assert TestClient(api).get('/health').json() == {'ok': True}
    assert go.Figure(go.Bar(x=['smoke'], y=[1])).to_json()

    settings = Settings.from_root(ROOT)
    auth = Authorization(settings)
    try:
        selected = auth.scenario
        data = catalog(selected)
        conn = auth.connection
        columns = conn.execute('SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema=%s ORDER BY table_name,ordinal_position', (selected,)).fetchall()
        constraints = conn.execute('SELECT table_name,constraint_name,constraint_type FROM information_schema.table_constraints WHERE table_schema=%s ORDER BY table_name,constraint_name', (selected,)).fetchall()
        indexes = conn.execute('SELECT tablename,indexname,indexdef FROM pg_catalog.pg_indexes WHERE schemaname=%s ORDER BY tablename,indexname', (selected,)).fetchall()
        for table, names in data['tables'].items():
            assert [c['column_name'] for c in columns if c['table_name']==table] == names
        assert all(c['data_type']=='text' for c in columns)
        counts = {table: conn.execute(f'SELECT COUNT(*) AS n FROM {selected}.{table}').fetchone()['n'] for table in data['tables']}
        with Bundle(settings, auth, Budget()) as bundle:
            quality = [q.model_dump() for q in check_quality(bundle)]
        previous = json.loads((ROOT/'reports/postgres_analytics_validation.json').read_text())
        previous_rows = previous['scenarios'][selected]['quality']['rows']
        assert counts['payments'] == previous_rows
        report = {'recorded_at':datetime.now(timezone.utc).isoformat(), 'selected_schema':selected,
                  'source':{'host':'127.0.0.1','port':settings.db_port,'database':'payments_analytics','role':'ai_analyst'},
                  'columns':columns,'constraints_visible_to_restricted_role':constraints,'indexes':indexes,
                  'counts':counts,'quality':quality,'dependency_smoke':'passed',
                  'versions':{dist.metadata['Name']:dist.version for dist in importlib.metadata.distributions()},
                  'saved_database_report_status':previous.get('status'),
                  'saved_payment_row_count_matches':True,
                  'saved_database_report_sha256':hashlib.sha256((ROOT/'reports/postgres_analytics_validation.json').read_bytes()).hexdigest(),
                  'catalog_mapping':'matches current database','scope_table_count':len(data['tables'])}
        (ROOT/'reports/analyst/schema_audit.json').write_text(json.dumps(report,indent=2)+'\n')
        print(f'Dependency smoke and read-only {selected} audit passed: {len(data["tables"])} tables.')
    finally:
        auth.close()


if __name__ == '__main__':
    main()
