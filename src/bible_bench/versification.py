"""Translate a verse reference between versification schemes.

Bible editions do not agree on how verses are numbered, and the disagreement is
not cosmetic: in the `lxx` and `rso` schemes the Psalms are renumbered wholesale,
so `PSA.23.1` is a *different psalm* than in `eng`, not a shifted verse. Three of
the eighteen translations this benchmark tests use those schemes. Asking all
eighteen for one reference without correcting for that would compare different
passages and report the difference as a model's accuracy.

Each edition declares its scheme in the Core API's ``version.json`` as ``vrs``.
This module turns that label into an actual reference translation, using the
Paratext rules vendored in ``dataset/versification/`` (see the README there).

`org` is the pivot: every scheme's table maps its own references to `org`, so a
translation between two arbitrary schemes composes forward then backward. Pure
functions over committed data — no network, no API, no per-language special case.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

# The scheme every mapping table pivots through.
ORG = "org"

_DATA_DIR = Path(__file__).resolve().parents[2] / "dataset" / "versification"
SCHEMES = ("eng", "org", "lxx", "rso", "rsc", "vul")


class VersificationError(RuntimeError):
    """A scheme we have no table for. Never guessed — a wrong mapping would
    silently score a model against the wrong verse."""


def _parse(ref: str) -> tuple[str, int, list[int]] | None:
    """``'PSA 3:0-8'`` → ``('PSA', 3, [0..8])``; ``'PSA 2:13'`` → ``('PSA', 2, [13])``.

    None for anything unparseable (sub-verse letters like ``'ACT 19:41a'``),
    which is correct: a mapping we can't represent per-verse is one we must not
    apply.
    """
    try:
        book, chapter_verse = ref.split(" ", 1)
        chapter, verses = chapter_verse.split(":")
        if "-" in verses:
            first, last = verses.split("-")
            span = list(range(int(first), int(last) + 1))
        else:
            span = [int(verses)]
        return book, int(chapter), span
    except (ValueError, TypeError):
        return None


@cache
def _table(scheme: str) -> dict:
    path = _DATA_DIR / f"{scheme}.json"
    if not path.is_file():
        raise VersificationError(
            f"No versification table for scheme {scheme!r} "
            f"(expected {path}). Vendor it from the Copenhagen Alliance spec."
        )
    return json.loads(path.read_text())


@cache
def _to_org(scheme: str) -> dict[str, str]:
    """``{scheme usfm → org usfm}``, non-identity entries only.

    Ranges are zipped element-wise. Where the two sides differ in length the
    shorter one clamps — that is the upstream convention for a many-to-one merge
    (two verses combined into one in the other scheme).
    """
    out: dict[str, str] = {}
    for src, dst in _table(scheme).get("mappedVerses", {}).items():
        parsed_src, parsed_dst = _parse(src), _parse(dst)
        if not parsed_src or not parsed_dst:
            continue
        (s_book, s_ch, s_verses), (d_book, d_ch, d_verses) = parsed_src, parsed_dst
        for i, verse in enumerate(s_verses):
            target = d_verses[min(i, len(d_verses) - 1)]
            key = f"{s_book}.{s_ch}.{verse}"
            value = f"{d_book}.{d_ch}.{target}"
            if key != value:
                out[key] = value
    return out


@cache
def _from_org(scheme: str) -> dict[str, str]:
    """The inverse of :func:`_to_org`.

    Many-to-one mappings make the inverse ambiguous; first-wins keeps it
    deterministic, and the tables are sorted so "first" is stable across runs.
    """
    inverse: dict[str, str] = {}
    for scheme_ref, org_ref in sorted(_to_org(scheme).items()):
        inverse.setdefault(org_ref, scheme_ref)
    return inverse


def to_org(usfm: str, scheme: str) -> str:
    """One reference, expressed in the `org` scheme."""
    if scheme == ORG:
        return usfm
    return _to_org(scheme).get(usfm, usfm)


def from_org(usfm: str, scheme: str) -> str:
    """One `org` reference, expressed in ``scheme``."""
    if scheme == ORG:
        return usfm
    return _from_org(scheme).get(usfm, usfm)


def translate(usfm: str, source: str, target: str) -> str:
    """``usfm`` as written in ``source``, re-expressed in ``target``.

    Composes through `org`. Returns the reference unchanged when both schemes
    agree about it, which is the common case — the tables only carry differences.
    """
    if source == target:
        return usfm
    for scheme in (source, target):
        if scheme not in SCHEMES:
            raise VersificationError(f"Unknown versification scheme {scheme!r}")
    return from_org(to_org(usfm, source), target)


def max_verses(book: str, chapter: int, scheme: str) -> int:
    """How many verses ``scheme`` gives that chapter, or 0 if it has no such
    chapter. Used to find a chapter's final verse without an API round-trip."""
    counts = _table(scheme).get("maxVerses", {}).get(book)
    if not counts or chapter < 1 or chapter > len(counts):
        return 0
    return int(counts[chapter - 1])


def chapter_count(book: str, scheme: str) -> int:
    """How many chapters ``scheme`` gives ``book`` (0 if the book is absent)."""
    return len(_table(scheme).get("maxVerses", {}).get(book, ()))


def scheme_has(usfm: str, scheme: str) -> bool:
    """Whether ``scheme`` numbers that reference at all.

    A scheme-level check only. An individual edition can still omit a verse its
    scheme allows, so this narrows candidates; the edition's own verse list is
    the authority (see BibleClient.chapter_verses).
    """
    try:
        book, chapter, verse = usfm.split(".")
        return 1 <= int(verse) <= max_verses(book, int(chapter), scheme)
    except (ValueError, VersificationError):
        return False
