from enum import Enum
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel, Field

from app.config import settings


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    role: MessageRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolFunctionSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, object]


class ToolDefinition(BaseModel):
    type: str = "function"
    function: ToolFunctionSpec


class ChatCompletionResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw: dict[str, object] = Field(default_factory=dict)


class LLMProvider(Protocol):
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> ChatCompletionResponse: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 15.0,
        extra_headers: dict[str, str] | None = None,
    ):
        self.api_key = api_key or settings.LLM_KEY
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://logmind.io",
            "X-Title": "LogMind SRE Investigator",
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        res = await client.post(url, json=payload, headers=headers)
        _ = res.raise_for_status()
        return cast(dict[str, Any], res.json())

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> ChatCompletionResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            payload["tools"] = [t.model_dump(exclude_none=True) for t in tools]

        data = await self._post(payload)

        choices = data.get("choices", [])
        if not choices:
            return ChatCompletionResponse(content=None, raw=data)

        first_msg = choices[0].get("message", {})
        content = first_msg.get("content")

        raw_calls = first_msg.get("tool_calls") or []
        parsed_calls: list[ToolCall] = []
        for c in raw_calls:
            fn = c.get("function", {})
            parsed_calls.append(
                ToolCall(
                    id=str(c.get("id", "")),
                    type=str(c.get("type", "function")),
                    function=ToolCallFunction(
                        name=str(fn.get("name", "")),
                        arguments=str(fn.get("arguments", "{}")),
                    ),
                )
            )

        return ChatCompletionResponse(
            content=content, tool_calls=parsed_calls, raw=data
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
