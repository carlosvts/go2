"""Cliente do `llama-server` (llama.cpp), num processo separado, por HTTP.

Usa a rota compatível com OpenAI (`/v1/chat/completions`) e o `/health`.
Prompt e parâmetros vêm de `llm/` (congelados na etapa 2 da E-002).
"""

from pathlib import Path

import httpx
import yaml

from app.reply.engine import Generation


class LlamaServer:
    def __init__(self, base_url: str, llm_dir: Path) -> None:
        params = yaml.safe_load((llm_dir / "generation.yaml").read_text(encoding="utf-8"))
        self.params = params
        self._system = (llm_dir / "prompt.md").read_text(encoding="utf-8").strip()
        self._client = httpx.AsyncClient(base_url=base_url)

    async def health(self, timeout_s: float) -> bool:
        try:
            response = await self._client.get("/health", timeout=timeout_s)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def generate(self, text: str, timeout_s: float) -> Generation:
        body = {
            "messages": [
                {"role": "system", "content": self._system},
                {"role": "user", "content": text},
            ],
            "max_tokens": int(self.params["max_tokens"]),
            "temperature": float(self.params["temperature"]),
            "top_p": float(self.params["top_p"]),
            "stream": False,
        }
        response = await self._client.post(
            "/v1/chat/completions", json=body, timeout=max(timeout_s, 0.001)
        )
        response.raise_for_status()
        data = response.json()
        content = str(data["choices"][0]["message"]["content"]).strip()
        tokens = (data.get("usage") or {}).get("completion_tokens")
        return Generation(content, tokens)

    async def aclose(self) -> None:
        await self._client.aclose()
