"""E-002: o pedido ao llama-server leva os parâmetros congelados de llm/."""

import json
from pathlib import Path

import httpx
import yaml

from app.reply.llama import LlamaServer

LLM_DIR = Path(__file__).resolve().parent.parent / "llm"


async def test_request_uses_frozen_parameters():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        answer = {
            "choices": [{"message": {"content": " Eu. Go2. "}}],
            "usage": {"completion_tokens": 4},
        }
        return httpx.Response(200, json=answer)

    llama = LlamaServer("http://llama", LLM_DIR, transport=httpx.MockTransport(handler))
    generation = await llama.generate("quem é você", timeout_s=1.0)
    await llama.aclose()
    params = yaml.safe_load((LLM_DIR / "generation.yaml").read_text(encoding="utf-8"))
    assert generation.text == "Eu. Go2." and generation.tokens == 4
    assert seen["max_tokens"] == params["max_tokens"] == 32
    assert seen["temperature"] == params["temperature"] == 0.4
    assert seen["top_p"] == 0.9 and seen["stop"] == ["\n"]
    assert seen["messages"][0]["role"] == "system"
    assert seen["messages"][1] == {"role": "user", "content": "quem é você"}


def test_model_hash_is_frozen():
    params = yaml.safe_load((LLM_DIR / "generation.yaml").read_text(encoding="utf-8"))
    assert len(params["model_sha256"]) == 64
