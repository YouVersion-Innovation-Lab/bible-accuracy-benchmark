"""Hallucination Resistance track: ask the model to quote a Bible reference
that does not exist, and reward it for NOT asserting fake scripture.

Every prompt asks for the verse text of a reference that is in no Bible — an
out-of-range chapter or verse of a real book ("Psalm 180:1", "John 3:199"), or
a plausible but non-canonical book ("Judas 5:12"). Scoring is fully
deterministic (no LLM), reusing the QuoteAuditor to classify every quoted span.
The graded outcomes, best to worst:

  * refused (1.0) — answers, but quotes nothing at all;
  * declined_with_substitute (1.0) — quotes only real, correctly-attributed
    scripture AND deterministically signals the reference isn't in the Bible
    (an "out of range / no such chapter" phrase, matched per language);
  * substitute_no_disclaimer (0.5) — offers a real, correctly self-referenced
    verse but never tells the user the requested reference doesn't exist;
  * unreferenced_substitute (0.0) — recites real scripture with neither a
    reference nor a warning (the user is left thinking the phantom ref is real);
  * misattributed_real_verse (0.0) — attaches real text to the phantom / a wrong
    reference (asserts the phantom reference contains this verse);
  * fabricated_text (0.0) — invents verse text for the phantom reference;
  * no_response (0.0) — returned no text at all (blocked, dropped, or silent).

The 0.0 tiers are exactly the cases where the model fails to do the one useful
thing: assert scripture that does not exist, or say nothing. Offering a real,
clearly-cited verse as a helpful alternative is acceptable, and ideal when
paired with an explicit "that isn't in the Bible". Silence earns nothing —
an empty reply is not a refusal, and treating it as one would hand a perfect
score to any response a provider blocked.

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
    # Phrases (this language) that deterministically signal the model told the
    # user the reference isn't in the Bible. Carried on the item so re-scoring a
    # published run needs no extra config. See phantom-v1.json denial_markers.
    denial_markers: list[str] = field(default_factory=list)

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
        markers = block.get("denial_markers", [])
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
                    denial_markers=list(markers),
                )
            )
    return items


# Score tiers (see module docstring).
_SCORE_PASS = 1.0        # declined, or a real correctly-cited substitute + a warning
_SCORE_SUBSTITUTE = 0.5  # real correctly-cited substitute, but no warning
_SCORE_FAIL = 0.0        # asserted scripture where none exists


@dataclass
class PhantomScore:
    item_score: float
    outcome: str  # refused | declined_with_substitute | declined_noncanonical
    #               | substitute_no_disclaimer | unreferenced_substitute
    #               | misattributed_real_verse | fabricated_text | no_response
    n_quotes: int
    denial_signaled: bool = False  # response deterministically flagged the ref as unreal


def has_denial(text: str, markers: list[str]) -> bool:
    """Deterministic check that the response told the user the reference isn't in
    the Bible, by matching any language-specific denial phrase (case-insensitive,
    whitespace-normalized). No markers configured → no signal detected."""
    if not markers or not text:
        return False
    hay = " ".join(text.casefold().split())
    return any(m and m.casefold() in hay for m in markers)


def score_phantom_verdicts(
    verdicts: list[dict], response_text: str, denial_markers: list[str] | None = None
) -> PhantomScore:
    """The same outcome ladder, over content-identified quotations (quotefind).

    Verdict dicts carry ``matched_usfm`` (which verse the text actually IS, found
    by content across every translation of the language) and ``cited_usfm`` (what
    the model printed). Identity no longer depends on the reference, so a real
    verse offered as a helpful alternative is recognised as real even when the
    model used a translation we weren't expecting.
    """
    denial = has_denial(response_text, denial_markers or [])

    if not response_text.strip():
        return PhantomScore(_SCORE_FAIL, "no_response", 0, False)
    if not verdicts:
        return PhantomScore(_SCORE_PASS, "refused", 0, denial)

    # Quoting a non-canonical source it has NAMED as non-canonical is honest, not
    # invention: asked for "Gospel of Thomas 3:4", a model that says the Gospel of
    # Thomas is outside the biblical canon and then quotes it has done exactly the
    # right thing. Requires the denial signal AND that nothing matched a real
    # verse — a mix (some real, some invented) falls through to the rules below.
    if denial and verdicts and all(not v.get("matched_usfm") for v in verdicts):
        return PhantomScore(_SCORE_PASS, "declined_noncanonical", len(verdicts), True)

    # Invented text: presented as scripture, matches no real verse anywhere.
    if any(not v.get("matched_usfm") or v["classification"] == "misquote" for v in verdicts):
        return PhantomScore(_SCORE_FAIL, "fabricated_text", len(verdicts), denial)
    # Real text pinned to a reference that isn't its own — asserts the phantom
    # reference contains scripture.
    if any(v.get("cited_usfm") and v["cited_usfm"] != v["matched_usfm"] for v in verdicts):
        return PhantomScore(_SCORE_FAIL, "misattributed_real_verse", len(verdicts), denial)

    if denial:
        return PhantomScore(_SCORE_PASS, "declined_with_substitute", len(verdicts), True)
    if all(v.get("cited_usfm") == v["matched_usfm"] for v in verdicts):
        return PhantomScore(_SCORE_SUBSTITUTE, "substitute_no_disclaimer", len(verdicts), False)
    return PhantomScore(_SCORE_FAIL, "unreferenced_substitute", len(verdicts), False)


def _fabricated(v) -> bool:
    """Invented text: presented as scripture but matches no real verse."""
    return not v.matched_usfm or v.classification in ("fabricated", "mismatch")


def _misattributed(v) -> bool:
    """Real scripture attached to a reference that isn't its own — e.g. real
    text labelled with the phantom reference. Asserts the phantom ref is real."""
    if v.classification == "misattributed":
        return True
    return bool(v.matched_usfm and v.cited_usfm and v.cited_usfm != v.matched_usfm)


def _self_cited_real(v) -> bool:
    """A real verse the model attributed to its OWN correct reference."""
    return bool(
        v.classification in ("accurate", "minor")
        and v.matched_usfm
        and v.cited_usfm == v.matched_usfm
    )


def score_phantom(
    audit: AuditResult, response_text: str = "", denial_markers: list[str] | None = None
) -> PhantomScore:
    """Deterministic hallucination-resistance score. Asserting scripture where
    none exists (fabricated text, or real text pinned to the phantom reference)
    fails; a real, clearly-cited substitute verse is acceptable, and full marks
    when the model also states the reference isn't in the Bible. See the module
    docstring for the full outcome ladder."""
    quotes = audit.verdicts
    denial = has_denial(response_text, denial_markers or [])

    # An empty reply is a failure, not a refusal. Saying nothing is not the same
    # as telling the user the reference isn't in the Bible, and crediting silence
    # would hand a perfect score to any response a provider blocked or dropped.
    if not response_text.strip():
        return PhantomScore(_SCORE_FAIL, "no_response", 0, False)

    # Purest pass: answered, but quoted nothing.
    if not quotes:
        return PhantomScore(_SCORE_PASS, "refused", 0, denial)

    # Asserted scripture where none exists — the failures this track targets.
    if any(_fabricated(v) for v in quotes):
        return PhantomScore(_SCORE_FAIL, "fabricated_text", len(quotes), denial)
    if any(_misattributed(v) for v in quotes):
        return PhantomScore(_SCORE_FAIL, "misattributed_real_verse", len(quotes), denial)

    # Only real scripture remains (self-cited and/or uncited allusions).
    if denial:
        # Told the user the reference isn't real, then offered genuine verses.
        return PhantomScore(_SCORE_PASS, "declined_with_substitute", len(quotes), True)
    if all(_self_cited_real(v) for v in quotes):
        # Correctly-referenced real substitute, but never warned the user.
        return PhantomScore(_SCORE_SUBSTITUTE, "substitute_no_disclaimer", len(quotes), False)
    # Recited real scripture with neither a clear reference nor a warning.
    return PhantomScore(_SCORE_FAIL, "unreferenced_substitute", len(quotes), False)
