"""Explicit browser-test app factory. Not a production provider or mode."""
import os
from types import SimpleNamespace
from insurelens.server import create_app
from tests.nim_fixture import ScriptedNim


def create_test_app():
    return create_app(root=os.environ["DATA_DIR"], nim=ScriptedNim(), drugs=SimpleNamespace(enabled=False))


def create_slow_test_app():
    import asyncio
    class SlowNim(ScriptedNim):
        async def chat(self, messages, model=None, **kwargs):
            await asyncio.sleep(7)
            return await super().chat(messages, model, **kwargs)
    return create_app(root=os.environ['DATA_DIR'], nim=SlowNim(), drugs=SimpleNamespace(enabled=False))


def create_conversation_test_app():
    from tests.nim_fixture import ConversationNim
    return create_app(root=os.environ['DATA_DIR'], nim=ConversationNim(), drugs=SimpleNamespace(enabled=False))


def create_drug_test_app():
    from tests.mfds_fixture import DrugNim, provider
    return create_app(root=os.environ['DATA_DIR'], nim=DrugNim(), drugs=provider())


def create_reset_test_app():
    import asyncio
    import json
    from tests.mfds_fixture import DrugNim, provider
    class WaitingNim(DrugNim):
        async def chat(self, messages, model=None, **kwargs):
            try:
                value = json.loads(messages[-1]['content'])
            except ValueError:
                return await ScriptedNim.chat(self, messages, model, **kwargs)
            if '대기' in value.get('query', ''):
                await asyncio.Event().wait()
            return await super().chat(messages, model, **kwargs)
    return create_app(root=os.environ['DATA_DIR'], nim=WaitingNim(), drugs=provider())
