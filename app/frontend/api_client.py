from pathlib import Path
import os

import httpx


class ResultVersionChanged(RuntimeError):
    pass


class ApiClient:
    def __init__(self, root=None):
        self.root = Path(os.environ.get('ANALYST_RUNTIME_ROOT', root or Path.cwd()))
        self.port = int(os.environ.get('ANALYST_API_PORT', '8000'))
        if not 1 <= self.port <= 65535:
            raise ValueError('Invalid local API port')

    def request(self, method, path, **kwargs):
        token_name = 'workspace_token' if path.startswith('/local/') else 'api_token'
        token_path = self.root / '.local/analyst' / token_name
        try:
            token = token_path.read_text().strip()
        except OSError:
            raise RuntimeError('Start or restart the analyst API to open the local workspace.') from None
        try:
            response = httpx.request(method, f'http://127.0.0.1:{self.port}' + path,
                                     headers={'Authorization':'Bearer '+token},
                                     timeout=15, trust_env=False, **kwargs)
        except httpx.HTTPError:
            raise RuntimeError('The local API is unavailable. Start the analyst and reopen your session.') from None
        if response.status_code == 422:
            detail = response.json().get('detail')
            if isinstance(detail, dict) and detail.get('status') in ('bank_filter', 'dimension_filter'):
                raise RuntimeError(detail['message'])
        if response.status_code == 409:
            detail = response.json().get('detail')
            if isinstance(detail, dict) and detail.get('status') == 'result_version_changed':
                raise ResultVersionChanged('The result changed. Review the refreshed result before choosing an action.')
            if isinstance(detail, dict) and detail.get('status') == 'stale':
                raise RuntimeError('Session authorization expired. Open Saved sessions to see the available conversations.')
            raise RuntimeError('The requested action conflicts with the current investigation. Refresh its status and check the selected scope.')
        if response.status_code in (401,403,404,410):
            raise RuntimeError('This session is unavailable. Open Saved sessions to choose a conversation.')
        if response.is_error:
            raise RuntimeError('The API could not complete the request. Inspect the local service status.')
        return response.json() if response.content else None
