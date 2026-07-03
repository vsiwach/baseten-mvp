"""Adapter interface conformance: every adapter implements the uniform
surface and advertises honest capabilities."""

import os
import unittest
from unittest import mock

from llm_app.adapter import BackendAdapter, ChatMessage, ChatRequest
from llm_app.openai_compat import (BasetenAdapter, BasetenModelAPIAdapter,
                                   VllmAdapter)
from llm_app.sim import MaxLocalSim


class InterfaceTest(unittest.TestCase):
    def _adapters(self):
        with mock.patch.dict(os.environ, {"BASETEN_API_KEY": "sk-test"}):
            return [
                MaxLocalSim("llm-sim"),
                VllmAdapter("qwen3-8b", base_url="http://pod:8000"),
                BasetenAdapter("qwen3-8b", base_url="http://b/production"),
                BasetenModelAPIAdapter(
                    "glm-4.7", base_url="https://inference.baseten.co",
                    model_id="zai-org/GLM-4.7"),
            ]

    def test_all_adapters_implement_the_interface(self):
        for a in self._adapters():
            self.assertIsInstance(a, BackendAdapter)
            self.assertIsInstance(a.info(), dict)
            self.assertEqual(a.capabilities(), {"chat"})
            self.assertIn(a.engine, ("max", "vllm", "baseten", "baseten-api"))

    def test_chat_adapters_refuse_predict(self):
        for a in self._adapters():
            with self.assertRaises(NotImplementedError):
                a.predict({})

    def test_sim_reports_warm_state(self):
        sim = MaxLocalSim("llm-sim")
        self.assertFalse(sim.info()["warm"])
        sim.generate(ChatRequest("llm-sim", [ChatMessage("user", "warm up")],
                                 max_tokens=4, seed=1))
        self.assertTrue(sim.info()["warm"])


if __name__ == "__main__":
    unittest.main()
