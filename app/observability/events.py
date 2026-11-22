import json
import threading
from datetime import datetime, timezone


class Events:
    def __init__(self,path):
        self.path = path
        self.lock = threading.Lock()

    def record(self, job, event, elapsed_ms=None, tool=None, details=None):
        data = {'time':datetime.now(timezone.utc).isoformat(), 'investigation_id':job.scope.investigation_id,
                'event':event,'status':job.status,'tool':tool,'elapsed_ms':elapsed_ms,
                'sql_statements':job.budget.statements,'tool_calls':job.budget.tools,
                'repairs':job.budget.repairs,'tokens_reserved':job.budget.tokens_reserved,
                'evidence_id':job.evidence.id if job.evidence else None,
                'error':job.error}
        if details is not None:
            data['details'] = details
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.lock, self.path.open('a',encoding='utf-8') as output:
            output.write(json.dumps(data)+'\n')
