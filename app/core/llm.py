from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class LLMClient(Protocol):
    def generate(self, system: str, prompt: str) -> str:
        ...


class RuleBasedLLM:
    """Deterministic fallback model for local demos and tests.

    The project is designed to plug in OpenAI, Qwen, DeepSeek, or internal
    enterprise gateways, but the fallback keeps the platform runnable offline.
    """

    def generate(self, system: str, prompt: str) -> str:
        lines = [line.strip() for line in prompt.splitlines() if line.strip()]
        focus = lines[-1] if lines else prompt[:120]
        return (
            f"{system}\n"
            f"基于当前证据，建议围绕“{focus[:80]}”进行结构化分析，"
            "优先保证结论可追溯、风险可解释、后续动作可执行。"
        )


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        current = os.environ.get(key)
        if current in (None, ""):
            os.environ[key] = value


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible HTTP client.

    Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL to use a real model gateway.
    This avoids binding the project to one provider and matches enterprise use.
    """

    def __init__(self) -> None:
        load_dotenv()
        self.base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("QWEN_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or ""
        ).rstrip("/")
        self.api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or ""
        )
        self.model = (
            os.getenv("LLM_MODEL")
            or os.getenv("QWEN_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "qwen-plus"
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def generate(self, system: str, prompt: str) -> str:
        if not self.configured:
            raise RuntimeError(
                "Real LLM is not configured. Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL."
            )

        import json
        import urllib.request

        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]


def build_llm(require_config: bool = False) -> LLMClient:
    load_dotenv()
    if os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY"):
        return OpenAICompatibleClient()
    if os.getenv("QWEN_BASE_URL") and os.getenv("DASHSCOPE_API_KEY"):
        return OpenAICompatibleClient()
    if os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_API_KEY"):
        return OpenAICompatibleClient()
    if require_config:
        raise RuntimeError(
            "Real LLM is required but not configured. Set LLM_BASE_URL/LLM_API_KEY or QWEN_BASE_URL/DASHSCOPE_API_KEY."
        )
    return RuleBasedLLM()
