"""Environment-driven configuration.

This repository is public: no API endpoint details, header names, header
values, or keys appear anywhere in code or version control. Everything needed
to reach the Bible API arrives via two env vars — an opaque base URL and an
opaque JSON object of request headers — provided out-of-band to authorized
operators (see .env.example for the variable names only).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BibleApiConfig:
    base_url: str
    headers: dict[str, str] = field(repr=False)  # never printed/logged
    max_concurrency: int = 8
    timeout_seconds: float = 30.0


def load_bible_api_config() -> BibleApiConfig:
    base_url = os.environ.get("YV_API_BASE_URL", "").strip()
    headers_raw = os.environ.get("YV_API_HEADERS", "").strip()
    missing = [
        name
        for name, val in [("YV_API_BASE_URL", base_url), ("YV_API_HEADERS", headers_raw)]
        if not val
    ]
    if missing:
        raise ConfigError(
            f"Missing required env var(s): {', '.join(missing)}. "
            "Bible API access credentials are provided out-of-band to authorized "
            "operators; copy .env.example to .env and fill them in."
        )
    try:
        headers = json.loads(headers_raw)
    except json.JSONDecodeError as e:
        raise ConfigError("YV_API_HEADERS must be a JSON object of request headers") from e
    if not isinstance(headers, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
    ):
        raise ConfigError("YV_API_HEADERS must be a JSON object mapping strings to strings")
    return BibleApiConfig(base_url=base_url.rstrip("/"), headers=headers)


@dataclass(frozen=True)
class LlmEndpointConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    label: str
    # OpenRouter `provider` routing block (openrouter.ai/docs → provider routing).
    # Applied ONLY when base_url is OpenRouter; withheld from native endpoints,
    # whose OpenAI-compat layers reject unknown body fields. Pins an open-weight
    # model to a fixed upstream/quantization so scores are reproducible.
    provider_routing: dict[str, object] | None = None


def _parse_provider_json(raw: str, source: str) -> dict | None:
    """Parse an OpenRouter ``provider`` routing object from a JSON string (or None)."""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"{source} must be a JSON object of OpenRouter provider routing"
        ) from e
    if not isinstance(obj, dict):
        raise ConfigError(f"{source} must be a JSON object of OpenRouter provider routing")
    return obj


def load_llm_endpoint(prefix: str) -> LlmEndpointConfig:
    """Load an OpenAI-compatible endpoint config from ``{prefix}_*`` env vars.

    Optional ``{prefix}_PROVIDER`` is a JSON object forwarded as OpenRouter's
    ``provider`` routing block (ignored for non-OpenRouter hosts) — e.g.
    ``{"order": ["fireworks"], "allow_fallbacks": false}`` to pin the attacker
    model to one upstream for reproducibility.
    """
    base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip()
    api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()
    model = os.environ.get(f"{prefix}_MODEL", "").strip()
    label = os.environ.get(f"{prefix}_LABEL", "").strip() or model
    missing = [
        f"{prefix}_{suffix}"
        for suffix, val in [("BASE_URL", base_url), ("API_KEY", api_key), ("MODEL", model)]
        if not val
    ]
    if missing:
        raise ConfigError(f"Missing required env var(s): {', '.join(missing)}")
    provider_routing = _parse_provider_json(
        os.environ.get(f"{prefix}_PROVIDER", "").strip(), f"{prefix}_PROVIDER"
    )
    return LlmEndpointConfig(
        base_url=base_url, api_key=api_key, model=model, label=label,
        provider_routing=provider_routing,
    )
