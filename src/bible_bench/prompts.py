"""Prompt rendering. Templates carry no verse text — only instruction wording
with placeholders filled at runtime from version metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .yv_client import BibleClient

_TEMPLATE_DIR = Path("dataset/templates")


@lru_cache(maxsize=1)
def _simple_templates() -> dict:
    return json.loads((_TEMPLATE_DIR / "simple.json").read_text())


async def render_simple_prompt(
    client: BibleClient, version_id: int, usfm: str, template_id: str, language_tag: str
) -> str:
    templates = _simple_templates()
    by_lang = templates["templates"][template_id]
    template = by_lang.get(language_tag) or templates["english_instruction_fallback"]
    meta = await client.version(version_id)
    reference = await client.human_reference(version_id, usfm)
    return template.format(
        reference=reference,
        version_title=meta.get("title") or meta.get("local_title") or meta.get("abbreviation", ""),
        version_abbrev=(meta.get("local_abbreviation") or meta.get("abbreviation", "")).upper(),
    )
