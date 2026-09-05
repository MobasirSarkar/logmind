from unittest.mock import AsyncMock, patch

import pytest

from investigation.client import (
    ChatCompletionResponse,
    ChatMessage,
    MessageRole,
    OpenAICompatibleClient,
    ToolDefinition,
    ToolFunctionSpec,
)


@pytest.mark.asyncio
async def test_llm_client_chat_completion_with_strong_types():
    client = OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-3.5-sonnet",
    )

    mock_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Root cause identified as payment gateway timeout.",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "get_trace",
                                "arguments": '{"trace_id": "tr-100"}',
                            },
                        }
                    ],
                }
            }
        ]
    }

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content="You are an SRE investigator."),
        ChatMessage(role=MessageRole.USER, content="Investigate incident in payment-service."),
    ]
    tools = [
        ToolDefinition(
            type="function",
            function=ToolFunctionSpec(
                name="get_trace",
                description="Retrieve trace execution tree",
                parameters={
                    "type": "object",
                    "properties": {"trace_id": {"type": "string"}},
                    "required": ["trace_id"],
                },
            ),
        )
    ]

    with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await client.chat_completion(messages=messages, tools=tools)

        assert isinstance(res, ChatCompletionResponse)
        assert res.content == "Root cause identified as payment gateway timeout."
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].id == "call_123"
        assert res.tool_calls[0].function.name == "get_trace"
        assert res.tool_calls[0].function.arguments == '{"trace_id": "tr-100"}'


@pytest.mark.asyncio
async def test_llm_client_handles_text_only_response():
    client = OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-3.5-sonnet",
    )

    mock_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Everything is normal.",
                }
            }
        ]
    }

    messages = [ChatMessage(role=MessageRole.USER, content="Status check")]
    with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await client.chat_completion(messages=messages)
        assert res.content == "Everything is normal."
        assert len(res.tool_calls) == 0
