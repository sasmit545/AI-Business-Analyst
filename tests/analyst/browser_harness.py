"""Browser-test API with a labeled model double; SQL and verification stay real."""
import json

from app.agent.graph import Investigator
from app.agent.model import ToolCall
from app.api.main import create_app
from app.config import Settings


class BrowserModelDouble:
    def next(self, messages, tools, budget):
        observations=[json.loads(m['content']) for m in messages if m['role']=='tool']
        if observations:
            return ToolCall('publish','publish_answer',{'evidence_id':observations[-1]['evidence_id']})
        return ToolCall('analyze','analyze_attempts',{
            'baseline':{'start':'2026-10-01T00:00:00+05:30','end':'2026-10-15T00:00:00+05:30'},
            'comparison':{'start':'2026-10-15T00:00:00+05:30','end':'2026-10-29T00:00:00+05:30'}})


settings=Settings.from_root()
app=create_app(settings=settings,runner_factory=lambda auth,store:Investigator(settings,auth,store,model=BrowserModelDouble()))
