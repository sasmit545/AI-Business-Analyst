"""Atomic, bounded, checksummed evidence; restart does not restore authorization."""
import hashlib
import json
import os
import threading
from pathlib import Path
from uuid import uuid4

from app.contracts import Evidence


def checksum(evidence):
    data = evidence.model_dump(mode='json', exclude={'checksum'})
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class EvidenceStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.steps = {}
        self.owners = {}
        self.lock = threading.RLock()

    def put(self, evidence, step):
        with self.lock:
            key = (evidence.scope.session_id, evidence.scope.investigation_id, step)
            if key in self.steps:
                previous = self.get(self.steps[key], evidence.scope)
                if previous.checksum != checksum(evidence):
                    raise ValueError('Step already has different evidence')
                return previous
            saved = evidence.model_copy(update={'checksum': checksum(evidence)})
            payload = saved.model_dump_json(indent=2)
            if len(payload.encode()) > 1024*1024:
                raise ValueError('Evidence artifact exceeds byte limit')
            target = self.directory / (saved.id + '.json')
            temporary = self.directory / (uuid4().hex + '.tmp')
            try:
                with temporary.open('x', encoding='utf-8') as file:
                    file.write(payload)
                    file.flush()
                    os.fsync(file.fileno())
                if target.exists():
                    raise ValueError('Evidence identity collision')
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            self.steps[key] = saved.id
            self.owners[saved.id] = saved.scope
            return saved

    def get(self, evidence_id, scope):
        with self.lock:
            if self.owners.get(evidence_id) != scope:
                raise PermissionError('Evidence unavailable for this investigation')
            data = (self.directory / (evidence_id + '.json')).read_text(encoding='utf-8')
            if len(data.encode()) > 1024*1024:
                raise ValueError('Evidence size invalid')
            evidence = Evidence.model_validate_json(data)
            if evidence.scope != scope or checksum(evidence) != evidence.checksum:
                raise ValueError('Evidence integrity failed')
            return evidence

    def forget_session(self, session_id):
        with self.lock:
            self.steps = {key: value for key, value in self.steps.items() if key[0] != session_id}
            self.owners = {key: scope for key, scope in self.owners.items() if scope.session_id != session_id}
