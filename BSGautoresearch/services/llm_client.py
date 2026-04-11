"""OpenRouter LLM client for autoresearch signal augmentation."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib import error, request

_LOGGER = logging.getLogger(__name__)

_ALLOWED_ROLES = {"controller", "model", "service", "middleware", "route", "config"}


class OpenRouterClient:
    """Small OpenRouter chat-completions client with strict JSON output parsing."""

    def __init__(self, llm_cfg: dict[str, Any]) -> None:
        self._cfg = dict(llm_cfg)
        self._enabled = bool(self._cfg.get("enabled", False))
        self._provider = str(self._cfg.get("provider", "")).strip().lower()
        self._api_base = str(self._cfg.get("api_base", "https://openrouter.ai/api/v1")).rstrip("/")
        self._model = str(self._cfg.get("model", "anthropic/claude-3.5-sonnet"))
        self._api_key_env = str(self._cfg.get("api_key_env", "OPENROUTER_API_KEY"))
        self._temperature = float(self._cfg.get("temperature", 0.0))
        self._max_tokens = int(self._cfg.get("max_tokens", 1200))
        self._timeout_sec = int(self._cfg.get("timeout_sec", 60))
        self._site_url = str(self._cfg.get("site_url", "")).strip()
        self._app_name = str(self._cfg.get("app_name", "batho-bsg-autoresearch")).strip()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def configured(self) -> bool:
        if not self._enabled:
            return False
        if self._provider != "openrouter":
            return False
        return bool(os.getenv(self._api_key_env, "").strip())

    def propose_signals(
        self,
        aggregated: dict[str, Any],
        *,
        max_signals: int = 6,
    ) -> list[dict[str, Any]]:
        """Return sanitized extra signals inferred by OpenRouter from mined stats."""

        if not self._enabled:
            return []
        if self._provider != "openrouter":
            _LOGGER.warning("llm provider unsupported", provider=self._provider)
            return []

        api_key = os.getenv(self._api_key_env, "").strip()
        if not api_key:
            _LOGGER.warning("openrouter api key missing", env=self._api_key_env)
            return []

        prompt = self._build_user_prompt(aggregated=aggregated, max_signals=max_signals)
        raw_response = self._chat(api_key=api_key, prompt=prompt)
        if raw_response is None:
            return []

        parsed = _extract_json_payload(raw_response)
        if not isinstance(parsed, dict):
            return []

        raw_signals = parsed.get("signals")
        if not isinstance(raw_signals, list):
            return []

        return _sanitize_signals(raw_signals, max_signals=max_signals)

    def _chat(self, *, api_key: str, prompt: str) -> str | None:
        endpoint = f"{self._api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if self._site_url:
            headers["HTTP-Referer"] = self._site_url
        if self._app_name:
            headers["X-Title"] = self._app_name

        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate deterministic JSON only. "
                        "Never return markdown fences unless explicitly requested."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(endpoint, data=data, headers=headers, method="POST")

        try:
            with request.urlopen(req, timeout=self._timeout_sec) as resp:
                response_data = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            _LOGGER.warning("openrouter http error", status=exc.code, body=body[:500])
            return None
        except error.URLError as exc:
            _LOGGER.warning("openrouter connection error", error=str(exc))
            return None
        except TimeoutError:
            _LOGGER.warning("openrouter timeout", timeout_sec=self._timeout_sec)
            return None

        try:
            payload = json.loads(response_data)
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                return None
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                return "\n".join(parts)
        except Exception:
            return None

        return None

    @staticmethod
    def _build_user_prompt(*, aggregated: dict[str, Any], max_signals: int) -> str:
        top_naming = aggregated.get("total_naming", {})
        top_motifs = aggregated.get("total_motif_counts", {})
        languages = aggregated.get("languages", [])
        repo_count = int(aggregated.get("repo_count", 0))

        return (
            "Generate extra deterministic BSG autoresearch signals.\n"
            "Output strict JSON object with key 'signals'.\n"
            "Each signal must be one of:\n"
            "1) {\"type\":\"naming_convention\",\"role\":<controller|model|service|middleware|route|config>,\"total_matches\":<int>}\n"
            "2) {\"type\":\"relationship_motif\",\"motif\":<string>,\"total_matches\":<int>}\n"
            f"Return at most {max_signals} signals, no duplicates, no explanations.\n"
            f"languages={json.dumps(languages)}\n"
            f"repo_count={repo_count}\n"
            f"top_naming={json.dumps(top_naming, sort_keys=True)}\n"
            f"top_motifs={json.dumps(top_motifs, sort_keys=True)}\n"
        )


def merge_signals(
    base_signals: list[dict[str, Any]],
    llm_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge and deduplicate base and LLM-proposed signals deterministically."""

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _key(signal: dict[str, Any]) -> tuple[str, str]:
        kind = str(signal.get("type", ""))
        if kind == "naming_convention":
            return kind, str(signal.get("role", ""))
        return kind, str(signal.get("motif", ""))

    for signal in list(base_signals) + list(llm_signals):
        key = _key(signal)
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(signal)

    merged.sort(
        key=lambda item: (
            str(item.get("type", "")),
            str(item.get("role", item.get("motif", ""))),
            -int(item.get("total_matches", 0)),
        )
    )
    return merged


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None

    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        snippet = text[first : last + 1]
        try:
            payload = json.loads(snippet)
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
    return None


def _sanitize_signals(
    raw_signals: list[Any],
    *,
    max_signals: int,
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []

    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue

        signal_type = str(raw.get("type", "")).strip().lower()
        if signal_type == "naming_convention":
            role = str(raw.get("role", "")).strip().lower()
            if role not in _ALLOWED_ROLES:
                continue
            total_matches = _as_positive_int(raw.get("total_matches"), fallback=1)
            cleaned.append(
                {
                    "type": "naming_convention",
                    "role": role,
                    "total_matches": total_matches,
                }
            )
            continue

        if signal_type == "relationship_motif":
            motif = str(raw.get("motif", "")).strip()
            if not motif:
                continue
            total_matches = _as_positive_int(raw.get("total_matches"), fallback=1)
            cleaned.append(
                {
                    "type": "relationship_motif",
                    "motif": motif,
                    "total_matches": total_matches,
                }
            )

    deduped = merge_signals([], cleaned)
    return deduped[:max_signals]


def _as_positive_int(value: Any, *, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed <= 0:
        return fallback
    return parsed
