"""Prompt rendering. Templates carry no verse text — only instruction wording
with placeholders filled at runtime from version metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .yv_client import BibleClient

_TEMPLATE_DIR = Path("dataset/templates")

# Sent as a system message on EVERY test, all tracks. Phrased conditionally so
# it never forces a model to quote (the implicit topical level must stay
# spontaneous) — it only standardizes the format WHEN a model chooses to quote,
# which is what lets the deterministic auditor find the quote and check it.
BENCHMARK_SYSTEM_PROMPT = (
    "When you quote text from the Bible, put the quoted words inside double "
    'quotation marks ("like this") and give the reference (book chapter:verse). '
    "Quote the wording exactly as it appears in the translation you are citing."
)


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
