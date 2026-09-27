"""Real NAT runtime tests using in-process fake agents; no files or network API."""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

from insurelens import nat as integration


@unittest.skipUnless(integration.nat_available(), "Install the nat extra")
class NativeNatTests(unittest.IsolatedAsyncioTestCase):
    def fake_module(self, fn):
        module = types.ModuleType("insurelens.agent")
        module.run_investigation = fn
        return patch.dict(sys.modules, {"insurelens.agent": module})

    def arguments(self, ident="one", emit=lambda *_: None):
        return {"document": {"id": ident, "pdf": "/private/source.pdf", "index": "/private/source.index"}, "request": {"query": ident}, "products": [], "nim": object(), "emit": emit}

    async def test_actual_nat_calls_python_and_preserves_callback(self):
        events, tokens = [], []
        args = self.arguments(emit=lambda event, data: events.append((event, data)))
        async def agent(**received):
            self.assertIs(received["nim"], args["nim"])
            self.assertIs(received["emit"], args["emit"])
            received["emit"]("stage_started", {"stage": "native"})
            return {"quotes": [{"quote": "변경 없는 원문"}], "mode": "local"}
        original = integration.invoke_native
        async def inspect(token):
            tokens.append(token)
            self.assertNotIn("/private", token)
            self.assertEqual(len(token), 32)
            return await original(token)
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "nat"}), patch.object(integration, "invoke_native", inspect), patch("asyncio.create_subprocess_exec", side_effect=AssertionError("NAT must not launch Node")):
            result = await integration._run_configured(**args)
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
            return {"quotes": [], "identity": args["document"]["id"], "mode": "local"}
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "nat"}):
            results = await asyncio.gather(*(integration._run_configured(**self.arguments(str(i))) for i in range(3)))
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
            task = asyncio.create_task(integration._run_configured(**self.arguments()))
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
                await integration._run_configured(**self.arguments())
        self.assertEqual(caught.exception.code, "NIM_RATE_LIMIT")
        self.assertEqual(caught.exception.status, 429)
        self.assertIsNone(integration._invocation.get())

    async def test_direct_mode_skips_nat_and_calls_same_agent(self):
        async def agent(**args):
            return {"quotes": [], "mode": "local"}
        with self.fake_module(agent), patch.dict(os.environ, {"AGENT_RUNNER": "direct"}), patch("nat.runtime.loader.load_workflow", side_effect=AssertionError("must bypass NAT")):
            self.assertEqual(await integration._run_configured(**self.arguments()), {"quotes": [], "mode": "local"})

    def test_auto_and_explicit_missing_runtime(self):
        with patch.object(integration, "nat_available", return_value=False):
            with patch.dict(os.environ, {"AGENT_RUNNER": "auto"}):
                self.assertEqual(integration.runner_mode(), "direct")
            with patch.dict(os.environ, {"AGENT_RUNNER": "nat"}):
                with self.assertRaisesRegex(Exception, "NAT_RUNTIME_MISSING"):
                    integration.runner_mode()
        with patch.dict(os.environ, {"AGENT_RUNNER": "auto"}):
            self.assertEqual(integration.runner_mode(), "nat")


if __name__ == "__main__":
    unittest.main()
