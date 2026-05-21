"""Auxiliary client helpers for hermes-lite.

These helpers power side tasks like context compression. Calls route through
``agent.llm_client.completion`` — Anthropic SDK for Claude, OpenAI SDK for
OpenAI-compatible endpoints (rvLLM, OpenRouter, etc.).
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional, Tuple

from agent.llm_client import completion as _completion


auxiliary_is_nous = False


class _CompletionsAdapter:
    def __init__(self, model: str, api_key: str, api_base: str = ""):
        self._model = model
        self._api_key = api_key
        self._api_base = api_base

    def create(self, **kwargs):
        kwargs.setdefault("model", self._model)
        kwargs.setdefault("api_key", self._api_key)
        if self._api_base:
            kwargs.setdefault("api_base", self._api_base)
        return _completion(**kwargs)


class _ChatShim:
    def __init__(self, adapter: _CompletionsAdapter):
        self.completions = adapter


class AuxiliaryClient:
    def __init__(self, model: str, api_key: str, api_base: str = ""):
        self.chat = _ChatShim(_CompletionsAdapter(model, api_key, api_base))
        self.api_key = api_key
        self.base_url = api_base


class _AsyncCompletionsAdapter:
    def __init__(self, sync_adapter: _CompletionsAdapter):
        self._sync = sync_adapter

    async def create(self, **kwargs):
        return await asyncio.to_thread(self._sync.create, **kwargs)


class _AsyncChatShim:
    def __init__(self, adapter: _AsyncCompletionsAdapter):
        self.completions = adapter


class AsyncAuxiliaryClient:
    def __init__(self, sync_client: AuxiliaryClient):
        sync_adapter = sync_client.chat.completions
        self.chat = _AsyncChatShim(_AsyncCompletionsAdapter(sync_adapter))
        self.api_key = sync_client.api_key
        self.base_url = sync_client.base_url


def get_text_auxiliary_client() -> Tuple[Optional[object], Optional[str]]:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        model = os.getenv("HERMES_AUX_MODEL", "").strip() or "claude-haiku-4-5"
        return AuxiliaryClient(model=model, api_key=anthropic_key), model

    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    if base_url:
        model = os.getenv("HERMES_AUX_MODEL", "").strip() or os.getenv("HERMES_LOCAL_AUX_MODEL", "").strip() or "local/qwen3.5-9b"
        api_key = os.getenv("OPENAI_API_KEY", "").strip() or "local"
        return AuxiliaryClient(model=model, api_key=api_key, api_base=base_url.rstrip("/")), model

    return None, None


def get_async_text_auxiliary_client():
    client, model = get_text_auxiliary_client()
    if client is None:
        return None, None
    if isinstance(client, AuxiliaryClient):
        return AsyncAuxiliaryClient(client), model
    return client, model


def get_vision_auxiliary_client() -> Tuple[Optional[object], Optional[str]]:
    return None, None


def get_auxiliary_extra_body() -> dict:
    return {}


def auxiliary_max_tokens_param(value: int) -> dict:
    return {"max_tokens": value}
