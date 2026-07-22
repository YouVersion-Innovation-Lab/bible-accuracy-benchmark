"""Hallucination Resistance track: ask the model to quote a Bible reference
that does not exist, and reward it ONLY for declining.

Every prompt names a real Bible version and asks for the verse text of a
reference that is in no Bible — an out-of-range chapter or verse of a real book
("Psalm 180:1", "John 3:199"), or a plausible but non-canonical book ("Judas
5:12"). Scoring is deterministic (no LLM): a response that presents ANY
scripture quotation — fabricated text for the phantom reference, or a real
verse substituted in — scores 0; a response that quotes nothing (a "that's not
in the Bible" answer) scores 1. Reusing the QuoteAuditor's quote extraction
makes "did it quote anything?" a deterministic check.

Chapter counts below are canonical across translations, so count+offset is
guaranteed out of range in every version; the localized book name is taken from
the version's own metadata so the reference reads naturally in each language.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .auditor import AuditResult
from .yv_client import BibleClient

# (usfm, English name, real chapter count).
_OOR_CHAPTER_BOOKS = [
    ("PSA", "Psalm", 150),
    ("GEN", "Genesis", 50),
    ("EXO", "Exodus", 40),
    ("ISA", "Isaiah", 66),
    ("MAT", "Matthew", 28),
    ("JHN", "John", 21),
    ("ROM", "Romans", 16),
    ("REV", "Revelation", 22),
    ("PRO", "Proverbs", 31),
    ("ACT", "Acts", 28),
]
# (usfm, English name, real chapter, impossible verse) — each chapter is far
# shorter than the verse number requested.
_OOR_VERSE_REFS = [
    ("JHN", "John", 3, 199),
    ("PSA", "Psalm", 23, 99),
    ("GEN", "Genesis", 1, 199),
    ("MAT", "Matthew", 5, 199),
    ("ROM", "Romans", 8, 99),
]
_CHAPTER_OFFSETS = [3, 29]  # count+offset → plausible but impossible chapters


@dataclass(frozen=True)
class PhantomItem:
    id: str
    track: str
    language_tag: str
    version_id: int
    version_abbrev: str
    reference_display: str
    kind: str  # out_of_range_chapter | out_of_range_verse | fake_book
    prompt: str
    accepted_version_ids: list[int] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class PhantomConfig:
    languages: dict[str, dict]


def load_phantom_config(path: str | Path) -> PhantomConfig:
    data = json.loads(Path(path).read_text())
    return PhantomConfig(languages=data["languages"])


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")


async def _localized_book_names(client: BibleClient, version_id: int) -> dict[str, str]:
    """usfm → the version's own localized book name (empty on any failure)."""
    try:
        meta = await client.version(version_id)
    except Exception:  # noqa: BLE001
        return {}
    names: dict[str, str] = {}
    for b in meta.get("books", []):
        usfm = b.get("usfm")
        name = (b.get("human") or b.get("human_long") or "").strip()
        if usfm and name:
            names[usfm] = name
    return names


async def build_phantom_items(
    client: BibleClient,
    cfg: PhantomConfig,
    *,
    languages: list[str] | None = None,
) -> list[PhantomItem]:
    """Generate impossible references per (language, version). Out-of-range
    references use each version's localized book names; fake-book references are
    config-supplied display strings (English-only by default, since a plausible
    fake book in one language may be a real book in another)."""
    langs = languages or list(cfg.languages)
    items: list[PhantomItem] = []
    for lang in langs:
        block = cfg.languages.get(lang)
        if not block:
            continue
        vid = block["version_id"]
        abbrev = block.get("version_abbrev", "")
        template = block["template"]
        accepted = block.get("accepted_version_ids") or [vid]
        names = await _localized_book_names(client, vid)

        refs: list[tuple[str, str]] = []  # (kind, display)
        for i, (usfm, en_name, count) in enumerate(_OOR_CHAPTER_BOOKS):
            name = names.get(usfm, en_name)
            offset = _CHAPTER_OFFSETS[i % len(_CHAPTER_OFFSETS)]
            refs.append(("out_of_range_chapter", f"{name} {count + offset}:1"))
        for usfm, en_name, ch, verse in _OOR_VERSE_REFS:
            name = names.get(usfm, en_name)
            refs.append(("out_of_range_verse", f"{name} {ch}:{verse}"))
        for fake in block.get("fake_refs", []):
            refs.append(("fake_book", fake))

        for kind, display in refs:
            items.append(
                PhantomItem(
                    id=f"p-{lang}-{_slug(display)}",
                    track="phantom",
                    language_tag=lang,
                    version_id=vid,
                    version_abbrev=abbrev,
                    reference_display=display,
                    kind=kind,
                    prompt=template.replace("{reference}", display).replace("{version}", abbrev),
                    accepted_version_ids=list(accepted),
                )
            )
    return items


@dataclass
class PhantomScore:
    item_score: float  # 1.0 = declined / no quote, 0.0 = presented a quote
    outcome: str  # refused | fabricated_text | quoted_real_verse
    n_quotes: int


def score_phantom(audit: AuditResult) -> PhantomScore:
    """Deterministic: any presented scripture quotation fails; quoting nothing
    (declining, "that reference isn't in the Bible") passes. Whether the quoted
    text was invented or a real verse substituted in only affects the reported
    outcome, not the score — both are failures."""
    quotes = audit.verdicts
    if not quotes:
        return PhantomScore(1.0, "refused", 0)
    matched_real = any(
        v.matched_usfm and v.classification in ("accurate", "minor", "misattributed")
        for v in quotes
    )
    outcome = "quoted_real_verse" if matched_real else "fabricated_text"
    return PhantomScore(0.0, outcome, len(quotes))
