"""Ollama client: local LLM chat, streaming, model discovery, and health checks.

Only the standard Ollama HTTP API is used, so TermX works with a stock
``ollama serve`` on the default port, a remote host, or a proxy.

Endpoints:
    GET  /api/tags       -> installed models
    GET  /api/version    -> server version
    POST /api/chat       -> chat completion (streaming or not)
    POST /api/show       -> model metadata
    POST /api/generate   -> raw completion
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import httpx

from termx.core.models import ConnectionState, ModelInfo

log = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
#: Known-good instruction-following models, best first. Used for fallbacks.
RECOMMENDED_MODELS = (
    "qwen2.5-coder:7b",
    "qwen2.5-coder:3b",
    "llama3.1:8b",
    "llama3.2:3b",
    "mistral:7b",
    "phi3:mini",
    "codellama:7b",
    "deepseek-coder:6.7b",
)


class OllamaError(RuntimeError):
    """Base error for Ollama interactions."""


class OllamaUnavailable(OllamaError):
    """The Ollama server could not be reached."""


class OllamaModelMissing(OllamaError):
    """The requested model is not installed."""


def normalize_host(host: str) -> str:
    """Normalise a user-entered host into a base URL."""
    value = (host or DEFAULT_HOST).strip().rstrip("/")
    if not value:
        value = DEFAULT_HOST
    if "://" not in value:
        value = f"http://{value}"
    return value


class OllamaClient:
    """Thin, typed wrapper around the Ollama REST API."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        timeout: float = 120.0,
        connect_timeout: float = 2.5,
        client: httpx.Client | None = None,
    ) -> None:
        self._host = normalize_host(host)
        self._timeout = timeout
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            headers={"Content-Type": "application/json", "User-Agent": "TermX/1.0"},
        )

    # -- configuration ------------------------------------------------------
    @property
    def host(self) -> str:
        return self._host

    def set_host(self, host: str) -> None:
        self._host = normalize_host(host)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _url(self, path: str) -> str:
        return f"{self._host}{path}"

    # -- health -------------------------------------------------------------
    def version(self) -> str:
        try:
            response = self._client.get(self._url("/api/version"), timeout=5.0)
            response.raise_for_status()
            return str(response.json().get("version", "unknown"))
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Ollama is not reachable at {self._host}") from exc

    def ping(self) -> tuple[ConnectionState, str]:
        """Return the connection state and a human-readable detail string."""
        try:
            response = self._client.get(self._url("/api/tags"), timeout=3.0)
            response.raise_for_status()
            payload = response.json()
            count = len(payload.get("models", []) or [])
            state = ConnectionState.CONNECTED if count else ConnectionState.DEGRADED
            return state, f"Ollama reachable — {count} model{'s' if count != 1 else ''} installed"
        except httpx.HTTPError as exc:
            return ConnectionState.OFFLINE, f"Cannot reach {self._host}: {type(exc).__name__}"
        except (json.JSONDecodeError, ValueError):
            return ConnectionState.DEGRADED, "Ollama responded with an unexpected payload"

    # -- models -------------------------------------------------------------
    def list_models(self) -> list[ModelInfo]:
        try:
            response = self._client.get(self._url("/api/tags"), timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Cannot list models: {exc}") from exc

        models: list[ModelInfo] = []
        for entry in response.json().get("models", []) or []:
            details: dict[str, Any] = entry.get("details") or {}
            modified = None
            if entry.get("modified_at"):
                try:
                    modified = datetime.fromisoformat(str(entry["modified_at"]).replace("Z", "+00:00"))
                except ValueError:
                    modified = None
            models.append(
                ModelInfo(
                    name=entry.get("name") or entry.get("model") or "unknown",
                    size_bytes=int(entry.get("size") or 0),
                    parameter_size=str(details.get("parameter_size") or ""),
                    quantization=str(details.get("quantization_level") or ""),
                    family=str(details.get("family") or ""),
                    modified_at=modified,
                )
            )
        models.sort(key=lambda m: m.name.lower())
        return models

    def model_names(self) -> list[str]:
        try:
            return [m.name for m in self.list_models()]
        except OllamaUnavailable:
            return []

    def has_model(self, name: str) -> bool:
        target = self._canonical(name)
        return any(self._canonical(existing) == target for existing in self.model_names())

    def resolve_model(self, preferred: str) -> str:
        """Return ``preferred`` if installed, else the best available model."""
        names = self.model_names()
        if not names:
            raise OllamaModelMissing("No models are installed. Run `ollama pull qwen2.5-coder:7b`.")
        target = self._canonical(preferred)
        for name in names:
            if self._canonical(name) == target:
                return name
        for recommended in RECOMMENDED_MODELS:
            for name in names:
                if name.lower().startswith(recommended.split(":")[0]):
                    return name
        return names[0]

    @staticmethod
    def _canonical(name: str) -> str:
        """Treat ``llama3`` and ``llama3:latest`` as the same model."""
        value = (name or "").strip().lower()
        if value and ":" not in value:
            value = f"{value}:latest"
        return value

    def show(self, model: str) -> dict[str, Any]:
        try:
            response = self._client.post(self._url("/api/show"), json={"model": model}, timeout=15.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Cannot inspect model '{model}': {exc}") from exc

    # -- chat ---------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.15,
        max_tokens: int = 1024,
        format_json: bool = False,
        timeout: float | None = None,
    ) -> str:
        """Send a chat request and return the full assistant message."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if format_json:
            payload["format"] = "json"
        try:
            response = self._client.post(
                self._url("/api/chat"),
                json=payload,
                timeout=timeout or self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise OllamaModelMissing(f"Model '{model}' is not installed. Run `ollama pull {model}`.") from exc
            raise OllamaError(f"Ollama returned {exc.response.status_code}: {exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc

        data = response.json()
        return str(((data.get("message") or {}).get("content")) or "").strip()

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.15,
        max_tokens: int = 1024,
        on_token: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """Yield assistant tokens as Ollama generates them."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            with self._client.stream("POST", self._url("/api/chat"), json=payload, timeout=self._timeout) as response:
                if response.status_code == 404:
                    raise OllamaModelMissing(f"Model '{model}' is not installed.")
                response.raise_for_status()
                for line in response.iter_lines():
                    if should_cancel and should_cancel():
                        return
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = str(((chunk.get("message") or {}).get("content")) or "")
                    if piece:
                        if on_token:
                            on_token(piece)
                        yield piece
                    if chunk.get("done"):
                        return
        except httpx.HTTPStatusError as exc:
            raise OllamaError(f"Ollama returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Streaming failed: {exc}") from exc

    def generate(
        self,
        prompt: str,
        model: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        format_json: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        if format_json:
            payload["format"] = "json"
        try:
            response = self._client.post(self._url("/api/generate"), json=payload, timeout=self._timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OllamaError(f"Ollama returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc
        return str(response.json().get("response") or "").strip()


def extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from a model reply."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {"answer": cleaned}
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        fragment = cleaned[start : end + 1]
        try:
            data = json.loads(fragment)
            return data if isinstance(data, dict) else {"answer": cleaned}
        except json.JSONDecodeError:
            # Attempt a light repair for truncated model output.
            repaired = fragment
            for _ in range(4):
                repaired += "}" if repaired.count("{") > repaired.count("}") else '"}'
                try:
                    data = json.loads(repaired)
                    return data if isinstance(data, dict) else {"answer": cleaned}
                except json.JSONDecodeError:
                    break
    return {"answer": cleaned}
