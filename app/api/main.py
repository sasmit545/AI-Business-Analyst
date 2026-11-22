import hmac
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Request
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from typing import Literal

from app.api.session import ResultVersionChanged, Sessions
from app.config import Settings
from app.context.banks import BankLookupError
from app.context.dimensions import DimensionLookupError
from app.contracts import AttemptDetail, Filters, StrictModel, Window
from app.query.executor import Authorization, BudgetExceeded, Cancelled, StaleSession
from app.ui_specs.models import Layout


class Question(StrictModel):
    question: str = Field(min_length=3,max_length=8000)


class Reply(StrictModel):
    version: int = Field(ge=1)
    answer: str = Field(min_length=3,max_length=8000)


class Resume(StrictModel):
    session_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    resume_key: str = Field(min_length=20,max_length=128)


class Followup(StrictModel):
    version: int = Field(ge=1)
    action: Literal['filter','test_hypothesis','point','windows','breakdown','question'] = 'filter'
    filters: Filters | None = None
    block: int | None = Field(default=None, ge=0, lt=6, strict=True)
    row: int | None = Field(default=None, ge=0, lt=400, strict=True)
    baseline: Window | None = None
    comparison: Window | None = None
    detail: AttemptDetail | None = None
    question: str | None = Field(default=None, min_length=3, max_length=4000)

    @model_validator(mode='after')
    def typed_action(self):
        required = {'filter':{'filters'}, 'test_hypothesis':set(), 'point':{'block','row'},
                    'windows':{'baseline','comparison'}, 'breakdown':{'detail'}, 'question':{'question'}}
        supplied = set(self.model_dump(exclude_none=True)) - {'action','version'}
        if supplied != required[self.action]:
            raise ValueError('Invalid parameters for follow-up action')
        return self


class Comparison(StrictModel):
    version: int = Field(ge=1)
    other_investigation_id: str = Field(pattern=r'^[0-9a-f]{32}$')


def create_app(settings=None, root=None, runner_factory=None, authorization_factory=Authorization, store_factory=None):
    root = Path(root or Path.cwd())

    @asynccontextmanager
    async def lifespan(api):
        configured = settings or Settings.from_root(root)
        if configured.host != '127.0.0.1':
            raise ValueError('Only loopback operation is supported')
        api.state.token = secrets.token_urlsafe(48)
        api.state.workspace_token = secrets.token_urlsafe(48)
        directory = root / '.local/analyst'
        directory.mkdir(parents=True, exist_ok=True)
        tokens = {directory/'api_token': api.state.token, directory/'workspace_token': api.state.workspace_token}
        for path, token in tokens.items():
            temporary = path.with_suffix('.tmp')
            temporary.write_text(token, encoding='utf-8')
            temporary.replace(path)
        api.state.sessions = Sessions(configured,root,runner_factory,authorization_factory,store_factory)
        try:
            yield
        finally:
            api.state.sessions.shutdown()
            for path, token in tokens.items():
                if path.exists() and path.read_text(encoding='utf-8') == token:
                    path.unlink()

    api = FastAPI(title='Payment analyst',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @api.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.headers.get('host','').split(':')[0]
        peer = request.client.host if request.client else ''
        origin = request.headers.get('origin')
        origin_host = urlsplit(origin).hostname if origin else None
        if host not in ('127.0.0.1','localhost','testserver') or peer not in ('127.0.0.1','::1','testclient'):
            return JSONResponse({'detail':'Loopback access only'},status_code=403)
        if origin_host is not None and origin_host not in ('127.0.0.1','localhost'):
            return JSONResponse({'detail':'Origin not allowed'},status_code=403)
        length = request.headers.get('content-length','0')
        if not length.isdigit() or int(length) > 65536:
            return JSONResponse({'detail':'Request too large'},status_code=413)
        return await call_next(request)

    def capability(authorization: str | None = Header(default=None)):
        expected = 'Bearer ' + api.state.token
        if not authorization or not hmac.compare_digest(authorization,expected):
            raise HTTPException(status_code=401,detail='Valid local capability required')

    def local_operator(authorization: str | None = Header(default=None)):
        if not authorization or not hmac.compare_digest(authorization, 'Bearer ' + api.state.workspace_token):
            raise HTTPException(status_code=401, detail='Local workspace access required')

    @api.exception_handler(StaleSession)
    async def stale(request,exc):
        return JSONResponse({'detail':{'status':'stale','message':'Session expired; start a new session'}},status_code=409)

    @api.exception_handler(KeyError)
    async def missing(request,exc):
        return JSONResponse({'detail':'Resource is not available in this session'},status_code=404)

    @api.exception_handler(BankLookupError)
    async def bank_filter(request, exc):
        return JSONResponse({'detail':{'status':'bank_filter', 'message':str(exc)}}, status_code=422)

    @api.exception_handler(DimensionLookupError)
    async def dimension_filter(request, exc):
        return JSONResponse({'detail':{'status':'dimension_filter', 'message':str(exc)}}, status_code=422)

    @api.exception_handler(ValueError)
    async def conflict(request,exc):
        return JSONResponse({'detail':'Request conflicts with the current investigation state'},status_code=409)

    @api.exception_handler(ResultVersionChanged)
    async def result_changed(request, exc):
        return JSONResponse({'detail':{'status':'result_version_changed'}}, status_code=409)

    @api.exception_handler(BudgetExceeded)
    async def budget(request,exc):
        return JSONResponse({'detail':'Investigation budget expired; start a new investigation'},status_code=409)

    @api.exception_handler(Cancelled)
    async def cancelled(request,exc):
        return JSONResponse({'detail':'Investigation was cancelled'},status_code=409)

    @api.get('/health',dependencies=[Depends(capability)])
    def health():
        return {'status':'ready'}

    @api.get('/ui/schema', dependencies=[Depends(capability)])
    def ui_schema():
        return Layout.model_json_schema()

    def session_summary(session):
        result={'session_id':session.id,'scenario':session.authorization.scenario, 'banks':session.authorization.banks,
                'investigation_ids':list(session.jobs)}
        if session.lease:
            result['resume_id']=session.stable_id
            if session.resume_key:
                result['resume_key']=session.resume_key
                session.resume_key=None
        return result

    @api.post('/sessions/resume',dependencies=[Depends(capability)])
    def resume(request: Resume):
        return session_summary(api.state.sessions.create(request.session_id,request.resume_key))

    def new_session(*, workspace):
        try:
            sessions = api.state.sessions
            with sessions.lock:
                return session_summary(sessions.create(local_operator=workspace))
        except (ValueError,StaleSession):
            raise
        except Exception:
            raise HTTPException(status_code=503,detail='Restricted database connection unavailable') from None

    @api.post('/sessions',dependencies=[Depends(capability)])
    def create_session():
        return new_session(workspace=False)

    @api.get('/local/sessions', dependencies=[Depends(local_operator)])
    def list_local_sessions():
        return {'sessions': api.state.sessions.saved()}

    @api.post('/local/sessions', dependencies=[Depends(local_operator)])
    def create_local_session():
        return new_session(workspace=True)

    @api.post('/local/sessions/{saved_id}/open', dependencies=[Depends(local_operator)])
    def open_local_session(saved_id: str = PathParam(pattern=r'^[0-9a-f]{32}$')):
        sessions = api.state.sessions
        with sessions.lock:
            return session_summary(sessions.create(saved_id, local_operator=True))

    @api.post('/sessions/{session_id}/detach',dependencies=[Depends(capability)])
    def detach(session_id: str):
        api.state.sessions.detach(session_id)
        return {'status':'detached'}

    @api.delete('/sessions/{session_id}',dependencies=[Depends(capability)])
    def close_session(session_id: str):
        api.state.sessions.close(session_id)
        return {'status':'closed'}

    @api.post('/sessions/{session_id}/investigations',dependencies=[Depends(capability)])
    def start(session_id: str, question: Question):
        return api.state.sessions.start(session_id,question.question).snapshot()

    @api.get('/sessions/{session_id}/history', dependencies=[Depends(capability)])
    def history(session_id: str):
        return api.state.sessions.history(session_id)

    @api.get('/sessions/{session_id}/investigations/{investigation_id}',dependencies=[Depends(capability)])
    def result(session_id: str, investigation_id: str):
        _,job = api.state.sessions.job(session_id,investigation_id)
        with job.lock:
            return dict(job.snapshot(), can_test_segment=job.can_test_segment())

    @api.post('/sessions/{session_id}/investigations/{investigation_id}/followup',dependencies=[Depends(capability)])
    def followup(session_id: str, investigation_id: str, command: Followup):
        return api.state.sessions.followup(session_id,investigation_id,command).snapshot()

    @api.post('/sessions/{session_id}/investigations/{investigation_id}/compare',dependencies=[Depends(capability)])
    def compare(session_id: str, investigation_id: str, command: Comparison):
        return api.state.sessions.compare(session_id,investigation_id,command.version,command.other_investigation_id)

    @api.post('/sessions/{session_id}/investigations/{investigation_id}/reply',dependencies=[Depends(capability)])
    def reply(session_id: str,investigation_id: str,reply: Reply):
        return api.state.sessions.reply(session_id,investigation_id,reply.version,reply.answer).snapshot()

    @api.post('/sessions/{session_id}/investigations/{investigation_id}/cancel',dependencies=[Depends(capability)])
    def cancel(session_id: str,investigation_id: str):
        return api.state.sessions.cancel(session_id,investigation_id).snapshot()

    @api.get('/sessions/{session_id}/evidence/{evidence_id}',dependencies=[Depends(capability)])
    def evidence(session_id: str,evidence_id: str):
        return api.state.sessions.evidence(session_id,evidence_id).model_dump(mode='json')

    return api


app = create_app()


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000,log_level='warning')
