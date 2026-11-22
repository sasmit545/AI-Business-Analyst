"""Private configuration is read by the host, never by model tools."""
import os
from pathlib import Path

from pydantic import Field, SecretStr

from app.contracts import StrictModel


def load_env(path: Path) -> None:
    """Read simple KEY=value lines without executing or interpolating their contents."""
    if not path.exists():
        return
    allowed = {'NVIDIA_API_KEY', 'ANALYST_MAX_TOKENS', 'ANALYST_FREE_CREDITS'}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        name, sep, value = line.strip().partition('=')
        if sep and name in allowed:
            os.environ.setdefault(name, value.strip().strip('"').strip("'"))


class Settings(StrictModel):
    host: str = '127.0.0.1'
    db_port: int = 5432
    db_password: SecretStr
    provider_key: SecretStr = SecretStr('')
    model: str = 'nvidia/nemotron-3.5-super-vl-120b-a12b'
    max_tokens: int = Field(default=32768, ge=1024, le=131072)
    free_credits: bool = True
    evidence_dir: Path = Path('.local/analyst/evidence')

    def model_post_init(self, context):
        if self.host != '127.0.0.1':
            raise ValueError('Only loopback operation is supported')

    @classmethod
    def from_root(cls, root: Path | None = None):
        import json
        root = root or Path.cwd()
        load_env(root / '.env')
        native = json.loads((root / '.local/postgres/native_config.json').read_text())
        return cls(db_port=native['port'],
                   db_password=SecretStr((root / '.local/postgres/ai_password').read_text().strip()),
                   provider_key=SecretStr(os.environ.get('NVIDIA_API_KEY', '')),
                   max_tokens=int(os.environ.get('ANALYST_MAX_TOKENS', '32768')),
                   free_credits=os.environ.get('ANALYST_FREE_CREDITS', 'true').lower() == 'true',
                   evidence_dir=root / '.local/analyst/evidence')
