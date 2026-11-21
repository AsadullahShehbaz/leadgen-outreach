import json
from typing import Any, Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel


class LLMClient(Protocol):
    async def complete(
        self,
        model: str,
        messages: list,
        schema: type[BaseModel] | None,
    ) -> Any:
        ...


class FakeLLMClient:
    """Deterministic no-network LLM for tests."""

    def __init__(self, responses: list[Any] | Any) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        model: str,
        messages: list,
        schema: type[BaseModel] | None,
    ) -> Any:
        self.calls.append({"model": model, "messages": messages, "schema": schema})
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, dict):
            if schema is not None:
                return schema.model_validate(response)
            return response
        if isinstance(response, str) and schema is not None:
            return schema.model_validate_json(response)
        return response


class GroqLLMClient:
    """Groq through its OpenAI-compatible chat completion API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.groq.com/openai/v1",
    ) -> None:
        if not api_key.strip():
            raise ValueError("Groq API key is required")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        model: str,
        messages: list,
        schema: type[BaseModel] | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        if schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty content")
        if schema is None:
            return json.loads(content)
        return schema.model_validate_json(content)

