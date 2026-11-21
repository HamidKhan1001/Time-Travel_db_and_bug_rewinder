"""Unit tests for BedrockProvider using mocked boto3 (stdlib unittest)."""
import json
import sys
import time
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from timetravel.llm._config import LLMConfig


def _make_tool_use_response(payload: dict) -> dict:
    """Fake the boto3 invoke_model response with Claude Tool Use shape."""
    body_text = json.dumps({
        "content": [
            {"type": "tool_use", "name": "structured_output", "input": payload}
        ]
    })
    return {"body": BytesIO(body_text.encode())}


class TestBedrockProvider(unittest.TestCase):
    def setUp(self):
        self.cfg = LLMConfig(
            api_key="",
            model="",
            timeout_s=5,
            min_confidence=0.7,
            explain_conflicts=True,
            provider="bedrock",
            bedrock_region="us-east-1",
            bedrock_model="anthropic.claude-3-haiku-20240307-v1:0",
        )

    def test_bedrock_success(self):
        expected = {"reason": "Order kept and flagged as backorder."}
        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke_model.return_value = _make_tool_use_response(expected)

        with patch.dict(sys.modules, {"boto3": mock_boto}):
            from timetravel.llm._provider import BedrockProvider
            provider = BedrockProvider(self.cfg)
            result = provider.generate_structured("prompt", {}, timeout_s=5)

        self.assertEqual(result, expected)

    def test_bedrock_no_tool_use_block(self):
        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        body_text = json.dumps({"content": [{"type": "text", "text": "oops"}]})
        mock_client.invoke_model.return_value = {"body": BytesIO(body_text.encode())}

        with patch.dict(sys.modules, {"boto3": mock_boto}):
            from timetravel.llm._provider import BedrockProvider
            provider = BedrockProvider(self.cfg)
            result = provider.generate_structured("prompt", {}, timeout_s=5)

        self.assertIsNone(result)

    def test_bedrock_aws_error(self):
        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke_model.side_effect = Exception("AccessDeniedException")

        with patch.dict(sys.modules, {"boto3": mock_boto}):
            from timetravel.llm._provider import BedrockProvider
            provider = BedrockProvider(self.cfg)
            result = provider.generate_structured("prompt", {}, timeout_s=5)

        self.assertIsNone(result)

    def test_bedrock_timeout(self):
        def slow_call(*a, **kw):
            time.sleep(5)

        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke_model.side_effect = slow_call

        with patch.dict(sys.modules, {"boto3": mock_boto}):
            from timetravel.llm._provider import BedrockProvider
            provider = BedrockProvider(self.cfg)
            result = provider.generate_structured("prompt", {}, timeout_s=1)

        self.assertIsNone(result)

    def test_bedrock_verifies_tool_choice_in_request(self):
        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        mock_client.invoke_model.return_value = _make_tool_use_response({})

        with patch.dict(sys.modules, {"boto3": mock_boto}):
            from timetravel.llm._provider import BedrockProvider
            provider = BedrockProvider(self.cfg)
            provider.generate_structured("prompt", {"type": "object"}, timeout_s=5)

        call_kwargs = mock_client.invoke_model.call_args[1]
        request_body = json.loads(call_kwargs["body"])
        self.assertEqual(request_body["tool_choice"], {"type": "tool", "name": "structured_output"})
        self.assertEqual(request_body["tools"][0]["input_schema"], {"type": "object"})


if __name__ == "__main__":
    unittest.main()
