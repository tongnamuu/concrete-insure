"""Real NAT runtime tests using in-process fake agents; no files or network API."""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

from insurelens import nat as integration


class NativeNatTests(unittest.IsolatedAsyncioTestCase):
    def fake_module(self, fn):
        module = types.ModuleType("insurelens.agent")
        module.run_investigation = fn
        return patch.dict(sys.modules, {"insurelens.agent": module})

    def arguments(self, ident="one", emit=lambda *_: None):
        return {"document": {"id": ident, "pdf": "/private/source.pdf", "index": "/private/source.index"}, "request": {"query": ident, "cloudConsent": True}, "products": [], "nim": types.SimpleNamespace(enabled=True), "emit": emit}

    async def test_actual_nat_calls_python_and_preserves_callback(self):
        events, tokens = [], []
        args = self.arguments(emit=lambda event, data: events.append((event, data)))
        async def agent(**received):
            self.assertIs(received["nim"], args["nim"])
            self.assertIs(received["emit"], args["emit"])
            received["emit"]("stage_started", {"stage": "native"})
            return {"quotes": [{"quote": "변경 없는 원문"}], "mode": "nim-react"}
        original = integration.invoke_native
        async def inspect(token):
            tokens.append(token)
            self.assertNotIn("/private", token)
            self.assertEqual(len(token), 32)
            return await original(token)
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "nat"}), patch.object(integration, "invoke_native", inspect), patch("asyncio.create_subprocess_exec", side_effect=AssertionError("NAT must not launch Node")):
            result = await integration.configured_investigation(**args)
        self.assertEqual(result["quotes"][0]["quote"], "변경 없는 원문")
        self.assertEqual(events, [("stage_started", {"stage": "native"})])
        self.assertEqual(len(tokens), 1)
        self.assertIsNone(integration._invocation.get())

    async def test_unbound_and_wrong_tokens_rejected(self):
        with self.assertRaisesRegex(ValueError, "NAT_INVOCATION_REQUIRED"):
            await integration.invoke_native('{"document":{"pdf":"/private/source.pdf"}}')
        token = integration._invocation.set(integration.Invocation("authorized", {}))
        try:
            with self.assertRaisesRegex(ValueError, "NAT_INVOCATION_REQUIRED"):
                await integration.invoke_native("wrong")
        finally:
            integration._invocation.reset(token)

    async def test_concurrent_invocations_keep_inputs_isolated(self):
        async def agent(**args):
            await asyncio.sleep(0.01)
            return {"quotes": [], "identity": args["document"]["id"], "mode": "nim-react"}
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "nat"}):
            results = await asyncio.gather(*(integration.configured_investigation(**self.arguments(str(i))) for i in range(3)))
        self.assertEqual([r["identity"] for r in results], ["0", "1", "2"])
        self.assertIsNone(integration._invocation.get())

    async def test_cancellation_reaches_python_agent(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def agent(**args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "nat"}):
            task = asyncio.create_task(integration.configured_investigation(**self.arguments()))
            await asyncio.wait_for(entered.wait(), 15)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cancelled.is_set())
        self.assertIsNone(integration._invocation.get())

    async def test_provider_error_type_survives_native_runtime(self):
        from insurelens.core import AppError
        async def agent(**args):
            raise AppError("NIM_RATE_LIMIT", 429)
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "nat"}):
            with self.assertRaises(AppError) as caught:
                await integration.configured_investigation(**self.arguments())
        self.assertEqual(caught.exception.code, "NIM_RATE_LIMIT")
        self.assertEqual(caught.exception.status, 429)
        self.assertIsNone(integration._invocation.get())

    async def test_legacy_runner_environment_cannot_bypass_nat(self):
        async def agent(**args):
            return {"quotes": [], "mode": "nim-react"}
        for old_mode in ("auto", "direct", "local"):
            with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": old_mode}), patch.object(integration, "load_workflow", wraps=integration.load_workflow) as workflow:
                await integration.configured_investigation(**self.arguments())
                self.assertEqual(workflow.call_count, 1)

    def test_missing_nat_import_is_fatal(self):
        import builtins
        import importlib.util
        from insurelens.core import AppError
        original = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == "nat" or name.startswith("nat."):
                raise ModuleNotFoundError("NAT missing", name="nat")
            return original(name, *args, **kwargs)
        spec = importlib.util.spec_from_file_location("missing_nat_fixture", integration.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"missing_nat_fixture": module}), patch("builtins.__import__", importing):
            with self.assertRaisesRegex(AppError, "NAT_RUNTIME_MISSING"):
                spec.loader.exec_module(module)

    async def test_no_key_or_consent_cannot_enter_workflow(self):
        from insurelens.core import AppError
        for enabled, consent, code in ((False, True, "NVIDIA_KEY_REQUIRED"), (True, False, "NIM_CONSENT_REQUIRED")):
            args = self.arguments()
            args["nim"] = types.SimpleNamespace(enabled=enabled)
            args["request"]["cloudConsent"] = consent
            with patch.object(integration, "load_workflow", side_effect=AssertionError("cannot enter workflow")):
                with self.assertRaisesRegex(AppError, code):
                    await integration.configured_investigation(**args)


if __name__ == "__main__":
    unittest.main()
