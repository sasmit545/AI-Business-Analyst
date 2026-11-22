from types import SimpleNamespace as NS
import pytest
from app.agent.model import ModelUnavailable, ModelOutputError, NemotronModel
from app.config import Settings
from app.query.executor import Budget, BudgetExceeded


def stream_chunk(arguments=None, finish=None, content=None):
    calls = [NS(index=0,id='call_1',function=NS(name='clarify',arguments=arguments))] if arguments is not None else None
    return NS(choices=[NS(delta=NS(tool_calls=calls,content=content,reasoning_content='private reasoning'),finish_reason=finish)])


class FakeStream:
    def __init__(self, chunks): self.chunks, self.closed = chunks, False
    def __iter__(self): return iter(self.chunks)
    def close(self): self.closed = True


class FakeClient:
    def __init__(self, chunks):
        self.stream = FakeStream(chunks)
        self.chat = NS(completions=NS(create=self.create))
    def create(self, **kwargs):
        self.request = kwargs
        return self.stream


def test_buffers_complete_tool_call_and_discards_prose_and_reasoning():
    client = FakeClient([stream_chunk('{"question":"Which dates?"}',content='unverified figure'),stream_chunk(finish='tool_calls')])
    result=NemotronModel(Settings(db_password='x'),client=client).next([{'role':'user','content':'question'}],[],Budget())
    assert result.name == 'clarify'
    assert result.arguments == {'question':'Which dates?'}
    assert 'reasoning' not in repr(result)
    assert 'unverified figure' not in repr(result)
    assert client.request['parallel_tool_calls'] is False
    assert client.stream.closed


def test_missing_key_and_truncated_or_malformed_output_fail_safely():
    with pytest.raises(ModelUnavailable):
        NemotronModel(Settings(db_password='x')).next([],[],Budget())
    for chunks in ([stream_chunk('{',finish='length')], [stream_chunk('{',finish='tool_calls')]):
        with pytest.raises(ModelOutputError):
            NemotronModel(Settings(db_password='x'),client=FakeClient(chunks)).next([],[],Budget())


def test_failed_call_consumes_token_reservation():
    budget=Budget()
    model=NemotronModel(Settings(db_password='x'),client=FakeClient([stream_chunk('{',finish='length')]))
    with pytest.raises(ModelOutputError): model.next([],[],budget)
    assert budget.tokens_reserved > 0
    budget.tokens_reserved=32768
    with pytest.raises(BudgetExceeded): model.next([],[],budget)


def test_provider_failure_does_not_echo_private_exception():
    class BrokenClient:
        def __init__(self): self.chat=NS(completions=NS(create=self.create))
        def create(self,**kwargs):
            exc=RuntimeError('private provider payload')
            exc.status_code=429
            raise exc
    budget=Budget()
    with pytest.raises(ModelUnavailable,match='rate limit') as failure:
        NemotronModel(Settings(db_password='x'),client=BrokenClient()).next([],[],budget)
    assert 'private' not in str(failure.value)
    assert budget.tokens_reserved > 0


def usage_chunk(prompt=1000, completion=200, total=1200):
    return NS(choices=[],usage=NS(prompt_tokens=prompt,completion_tokens=completion,total_tokens=total))


def test_completed_usage_leaves_budget_for_publication_after_repairs():
    budget=Budget()
    client=FakeClient([stream_chunk('{"topic":"windows"}',finish='tool_calls'),usage_chunk()])
    model=NemotronModel(Settings(db_password='x'),client=client)
    # Two repairs, analysis, then a larger evidence-bearing publication prompt.
    # These sizes reproduce reservation exhaustion without claiming live tokens.
    for size in (4500,5000,5500,13000):
        model.next([{'role':'user','content':'x'*size}],[],budget)
    assert budget.tokens_reserved == 4*1200
    assert client.request['stream_options']=={'include_usage':True}


@pytest.mark.parametrize('usage',[
    None,usage_chunk(total=1),usage_chunk(prompt=-1,total=199),
    usage_chunk(prompt=True,total=201),usage_chunk(prompt='1000'),
])
def test_missing_or_invalid_usage_keeps_full_reservation(usage):
    budget=Budget()
    chunks=[stream_chunk('{"topic":"windows"}',finish='tool_calls')]
    if usage is not None:
        chunks.append(usage)
    NemotronModel(Settings(db_password='x'),client=FakeClient(chunks)).next([],[],budget)
    assert budget.tokens_reserved > 4096


def test_interrupted_stream_keeps_reservation_even_after_usage():
    def interrupted():
        yield stream_chunk('{"topic":"windows"}',finish='tool_calls')
        yield usage_chunk()
        raise OSError('private interruption')
    budget=Budget()
    with pytest.raises(ModelUnavailable):
        NemotronModel(Settings(db_password='x'),client=FakeClient(interrupted())).next([],[],budget)
    assert budget.tokens_reserved > 4096


def test_reported_usage_above_ceiling_stops_investigation():
    budget=Budget()
    client=FakeClient([stream_chunk('{"topic":"windows"}',finish='tool_calls'),usage_chunk(33000,200,33200)])
    with pytest.raises(BudgetExceeded,match='token limit'):
        NemotronModel(Settings(db_password='x'),client=client).next([],[],budget)
    assert budget.tokens_reserved==33200


def test_usage_before_more_output_is_not_a_final_receipt():
    budget=Budget()
    chunks=[stream_chunk('{"topic":"windows"}',finish='tool_calls'),usage_chunk(),
            stream_chunk(content='additional output')]
    NemotronModel(Settings(db_password='x'),client=FakeClient(chunks)).next([],[],budget)
    assert budget.tokens_reserved > 4096
