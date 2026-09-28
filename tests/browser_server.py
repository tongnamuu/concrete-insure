"""Explicit browser-test app factory. Not a production provider or mode."""
import os
from types import SimpleNamespace
from concreteinsure.server import create_app
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
    from concreteinsure.core import AppError
    from tests.mfds_fixture import DrugNim, provider
    release = asyncio.Event()
    class WaitingNim(DrugNim):
        input_calls = 0
        async def chat(self, messages, model=None, **kwargs):
            self.input_calls += 1
            value = json.loads(messages[-1]['content'])
            query = value.get('query', '')
            if query == '실패 검사':
                raise AppError('NIM_TIMEOUT', 504)
            if '취소 대기' in query:
                await asyncio.Event().wait()
            elif '대기' in query:
                await release.wait()
            return await super().chat(messages, model, **kwargs)
    nim = WaitingNim()
    app = create_app(root=os.environ['DATA_DIR'], nim=nim, drugs=provider())
    # Test-only controls must precede the catch-all static mount.
    static_mount = app.router.routes.pop()

    @app.get('/_test/calls')
    async def calls():
        return {'input': nim.input_calls, 'tools': len(nim.calls)}

    @app.post('/_test/release')
    async def release_waiting():
        release.set()
        return {'ok': True}

    app.router.routes.append(static_mount)
    return app
