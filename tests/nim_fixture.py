"""Scripted NIM response fixture, injected only by test app factories.

No production environment switch enables this class. Actual NAT orchestration,
PDF operations, schema validation, and source verification are exercised.
"""
import json
import re
from concreteinsure.core import AppError, literal_terms


class ScriptedNim:
    enabled = True

    def __init__(self, fail_code=None):
        self.fail_code = fail_code
        self.calls = []

    async def chat(self, messages, model=None, **kwargs):
        self.calls.append("chat")
        if self.fail_code:
            raise AppError(self.fail_code, 504)
        text = messages[-1]["content"]
        try:
            value = json.loads(text)
        except ValueError:
            value = None
        if isinstance(value, dict):
            terms = literal_terms(value.get("query", ""), value.get("confirmedTerms", [])) + literal_terms(value.get("description", ""))
        else:
            terms = [m.strip() for m in re.findall(r"(?:약품명|제품명|성분명|질병코드|Drug|Ingredient)\s*[:：]\s*([^\n]+)", text, re.I)]
        return json.dumps({"terms": list(dict.fromkeys(terms))[:25]}, ensure_ascii=False)

    async def complete(self, messages, tools):
        self.calls.append("complete")
        if self.fail_code:
            raise AppError(self.fail_code, 504)
        payload = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
        observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not observations:
            name, arguments, identifier = "search_policy", {"ids": [t["id"] for t in payload["terms"][:10]]}, "fixture-search"
        elif len(observations) == 1 and observations[0].get("hits"):
            name, arguments, identifier = "read_context", {"hitId": observations[0]["hits"][0]["id"]}, "fixture-context"
        else:
            name, arguments, identifier = "finish_retrieval", {}, "fixture-finish"
        return {"finish_reason":"tool_calls", "message":{"role":"assistant", "content":None, "tool_calls":[{"id":identifier,"type":"function","function":{"name":name,"arguments":json.dumps(arguments)}}]}}

    async def close(self):
        pass


class ConversationNim(ScriptedNim):
    """Explicit follow-up fixture that requires real server context to resolve a referent."""
    def __init__(self):
        super().__init__()
        self.inputs = []
        self.plans = []

    async def chat(self, messages, model=None, **kwargs):
        value = json.loads(messages[-1]['content'])
        self.inputs.append(value)
        if value.get('query') == '실패 요청':
            raise AppError('NIM_TIMEOUT', 504)
        if value.get('query') == '그 경우 제외사항은?':
            history = value.get('conversation', [])
            terms = history[-1]['terms'] + ['제외사항'] if history else []
            return json.dumps({'terms': list(dict.fromkeys(terms))[:25]}, ensure_ascii=False)
        return await super().chat(messages, model, **kwargs)

    async def complete(self, messages, tools):
        self.plans.append(json.loads(next(m['content'] for m in messages if m['role'] == 'user')))
        return await super().complete(messages, tools)
