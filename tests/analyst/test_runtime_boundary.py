import ast
import json
from pathlib import Path

from app.config import Settings, load_env
from app.context.catalog import catalog


def test_runtime_has_no_admin_or_evaluator_imports():
    for path in Path('app').rglob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('scripts', 'evaluation', 'subprocess'))
            if isinstance(node, ast.Import):
                assert all(not name.name.startswith(('scripts', 'evaluation', 'subprocess')) for name in node.names)
    context = json.dumps(catalog('lifecycle_v1'))
    for prohibited in ('expected_answers', '193948', '199734', 'seed', 'postgres_password'):
        assert prohibited not in context


def test_env_does_not_override_existing_or_load_arbitrary_names(tmp_path, monkeypatch):
    monkeypatch.setenv('NVIDIA_API_KEY', 'existing-private-value')
    path = tmp_path / '.env'
    path.write_text('NVIDIA_API_KEY=other\nUNRELATED_SECRET=x\n')
    load_env(path)
    import os
    assert os.environ['NVIDIA_API_KEY'] == 'existing-private-value'
    assert 'UNRELATED_SECRET' not in os.environ
    settings = Settings(db_password='private-db-value', provider_key='private-model-value')
    assert 'private-db-value' not in settings.model_dump_json()
    assert 'private-model-value' not in repr(settings)
