"""Transport tests use httpx.MockTransport; no real API key or network required."""

import json
import os
import unittest
from unittest.mock import patch

import httpx

from relayops.provider import OpenAIProvider, ProviderError, SYSTEM, TOOLS, configured


def completed(**extra):
    return {"status": "completed", "output": [{"type": "function_call", "call_id": "call_1",
             "name": "read_export_evidence", "arguments": "{}"}],
            "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}, **extra}


class ProviderTests(unittest.TestCase):
    def client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def provider(self, handler):
        return OpenAIProvider(client=self.client(handler), model="configured-test-model", api_key="not-a-real-secret")

    def test_request_is_stateless_and_returns_structured_calls(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=completed())
        provider = self.provider(handler)
        messages = [{"role": "user", "content": "Investigate the selected case"}]
        result = provider.next(messages)
        request = requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
        self.assertEqual(request.headers["authorization"], "Bearer not-a-real-secret")
        self.assertEqual(body["model"], "configured-test-model")
        self.assertEqual(body["input"], messages)
        self.assertEqual(body["instructions"], SYSTEM)
        self.assertEqual(body["tools"], TOOLS)
        self.assertEqual(body["tool_choice"], "required")
        self.assertFalse(body["parallel_tool_calls"])
        self.assertFalse(body["store"])
        self.assertIn("reasoning.encrypted_content", body["include"])
        self.assertEqual(result["calls"][0]["name"], "read_export_evidence")
        self.assertEqual(result["usage"]["total_tokens"], 7)

    def test_reasoning_items_preserved_for_stateless_continuation(self):
        body = completed()
        body["output"].insert(0, {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque-test-payload"})
        provider = self.provider(lambda request: httpx.Response(200, json=body))
        result = provider.next([])
        self.assertEqual(result["output"], body["output"])
        self.assertEqual(len(result["calls"]), 1)

    def test_repair_can_supply_narrow_custom_tool_and_instructions(self):
        observed = []
        def handler(request):
            observed.append(json.loads(request.content))
            return httpx.Response(200, json=completed())
        self.provider(handler).next([], tools=[{"type": "function", "name": "propose_expression"}], instructions="Restricted repair")
        self.assertEqual(observed[0]["instructions"], "Restricted repair")
        self.assertEqual(observed[0]["tools"], [{"type": "function", "name": "propose_expression"}])

    def test_http_errors_do_not_expose_response_body_or_key(self):
        for status in (301, 400, 401, 429, 500):
            with self.subTest(status=status):
                provider = self.provider(lambda request: httpx.Response(status, text="private-upstream-body not-a-real-secret"))
                with self.assertRaises(ProviderError) as error:
                    provider.next([])
                self.assertIn(f"HTTP {status}", str(error.exception))
                self.assertNotIn("private-upstream", str(error.exception))
                self.assertNotIn("not-a-real-secret", str(error.exception))

    def test_network_errors_and_timeouts_have_safe_messages(self):
        for exception in (httpx.ConnectError, httpx.ReadTimeout):
            with self.subTest(exception=exception):
                def handler(request):
                    raise exception("private-upstream-body not-a-real-secret", request=request)
                provider = self.provider(handler)
                with self.assertRaises(ProviderError) as error:
                    provider.next([])
                self.assertNotIn("private-upstream", str(error.exception))
                self.assertNotIn("not-a-real-secret", str(error.exception))

    def test_invalid_json_incomplete_or_text_only_output_rejected(self):
        responses = [
            lambda: httpx.Response(200, text="not json"),
            lambda: httpx.Response(200, json=completed(status="incomplete")),
            lambda: httpx.Response(200, json=completed(output="invalid")),
            lambda: httpx.Response(200, json=completed(output=[{"type": "message", "content": "I fixed it"}])),
            lambda: httpx.Response(200, json=completed(output=[{}] * 31)),
        ]
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(ProviderError):
                    self.provider(lambda request: response()).next([])

    def test_invalid_tool_calls_rejected(self):
        for updates in ({"call_id": None}, {"name": None}, {"arguments": "not json"},
                        {"arguments": "[]"}, {"arguments": "null"}, {"arguments": 42}):
            with self.subTest(updates=updates):
                body = completed()
                body["output"][0].update(updates)
                with self.assertRaises(ProviderError):
                    self.provider(lambda request: httpx.Response(200, json=body)).next([])

    def test_oversized_response_rejected(self):
        with self.assertRaises(ProviderError) as error:
            self.provider(lambda request: httpx.Response(200, content=b"x" * 2_000_001)).next([])
        self.assertIn("size", str(error.exception))

    def test_settings_required_and_configuration_probe_consistent(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(configured())
            with self.assertRaises(ProviderError):
                OpenAIProvider()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture", "RELAYOPS_MODEL": "test-model"}, clear=True):
            self.assertTrue(configured())

    def test_borrowed_client_not_closed_by_provider(self):
        client = self.client(lambda request: httpx.Response(200, json=completed()))
        provider = OpenAIProvider(client=client, model="test", api_key="fixture")
        provider.close()
        self.assertFalse(client.is_closed)

    def test_non_object_json_response_has_safe_provider_error(self):
        for body in ([], None, "unexpected text", 42):
            with self.subTest(body=body):
                with self.assertRaises(ProviderError):
                    self.provider(lambda request: httpx.Response(200, json=body)).next([])

    def test_malformed_optional_usage_normalized_for_consumer(self):
        for usage in (None, [], "unexpected text", 42):
            with self.subTest(usage=usage):
                result = self.provider(lambda request: httpx.Response(200, json=completed(usage=usage))).next([])
                self.assertEqual(result["usage"], {})
                self.assertEqual(len(result["calls"]), 1)


if __name__ == "__main__":
    unittest.main()
