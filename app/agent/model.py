"""NVIDIA Chat Completions adapter. Only completed structured calls escape it."""
import json
import time
from dataclasses import dataclass

from app.query.executor import BudgetExceeded, Cancelled


class ModelUnavailable(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    pass


class InsufficientModelAllowance(BudgetExceeded):
    """The next call cannot be reserved. No request was issued."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


class NemotronModel:
    def __init__(self, settings, client=None):
        self.settings, self.client = settings, client

    def _client(self):
        if self.client is not None:
            return self.client
        if not self.settings.provider_key.get_secret_value():
            raise ModelUnavailable('NVIDIA_API_KEY is not configured')
        if not self.settings.free_credits:
            raise ModelUnavailable('Paid usage requires an explicit pricing and spend policy')
        try:
            from openai import OpenAI
        except ImportError:
            raise ModelUnavailable('The openai SDK is not installed') from None
        self.client = OpenAI(base_url='https://integrate.api.nvidia.com/v1',
                             api_key=self.settings.provider_key.get_secret_value(),
                             max_retries=0, timeout=15)
        return self.client

    def next(self, messages, tools, budget):
        budget.check()
        client = self._client()
        input_bound = len(json.dumps({'messages':messages,'tools':tools},ensure_ascii=False).encode('utf-8')) + 256
        available = self.settings.max_tokens - budget.tokens_reserved - input_bound
        publishing = any(t['function']['name'] == 'publish_answer' for t in tools)
        output_limit = min(1536 if publishing else 4096, available)
        if output_limit < 512:
            raise InsufficientModelAllowance('Investigation token limit reached')
        budget.reserve_tokens(input_bound + output_limit)
        chunks = None
        accumulated = {}
        finish = None
        usage = None
        byte_count = 0
        try:
            chunks = client.chat.completions.create(
                model=self.settings.model, messages=messages, tools=tools,
                tool_choice='required', temperature=1, top_p=0.95,
                max_tokens=output_limit, parallel_tool_calls=False, seed=42,
                extra_body={'chat_template_kwargs':{'enable_thinking':not publishing}},
                stream_options={'include_usage':True},
                stream=True, timeout=max(1,min(15,120-(time.monotonic()-budget.started))))
            for chunk in chunks:
                budget.check()
                if not chunk.choices:
                    if finish is not None:
                        usage = getattr(chunk,'usage',None)
                    continue
                usage = None
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish = choice.finish_reason
                for delta in getattr(choice.delta,'tool_calls',None) or []:
                    if delta.index not in accumulated:
                        accumulated[delta.index] = {'id':'','name':'','arguments':''}
                    item = accumulated[delta.index]
                    if delta.id:
                        item['id'] = delta.id
                    if delta.function:
                        if delta.function.name:
                            item['name'] += delta.function.name
                        if delta.function.arguments:
                            item['arguments'] += delta.function.arguments
                            byte_count += len(delta.function.arguments.encode())
                    if len(accumulated) > 1 or byte_count > 65536:
                        raise ModelOutputError('Provider returned excessive tool output')
            # Settle only after normal stream exhaustion and a final usage receipt.
            # Interrupted or unmetered calls retain their full reservation.
            counts = [getattr(usage,key,None) for key in ('prompt_tokens','completion_tokens','total_tokens')]
            if (all(type(value) is int and value >= 0 for value in counts)
                    and counts[0] > 0 and counts[2] == counts[0] + counts[1]):
                budget.settle_tokens(input_bound + output_limit, counts[2])
                if budget.tokens_reserved > self.settings.max_tokens:
                    raise BudgetExceeded('Investigation token limit reached')
            if finish != 'tool_calls' or len(accumulated) != 1:
                raise ModelOutputError('Provider did not complete one tool call')
            item = next(iter(accumulated.values()))
            try:
                args = json.loads(item['arguments'])
            except (ValueError, TypeError):
                raise ModelOutputError('Provider returned invalid tool arguments') from None
            if not item['id'] or not item['name'] or not isinstance(args,dict):
                raise ModelOutputError('Provider returned an invalid tool envelope')
            return ToolCall(item['id'],item['name'],args)
        except (ModelOutputError, BudgetExceeded, Cancelled):
            raise
        except Exception as exc:
            status = getattr(exc,'status_code',None)
            message = 'Provider rate limit reached' if status == 429 else 'Provider request failed or timed out'
            raise ModelUnavailable(message) from None
        finally:
            if chunks is not None:
                chunks.close()

    def close(self):
        if self.client is not None and hasattr(self.client,'close'):
            self.client.close()
