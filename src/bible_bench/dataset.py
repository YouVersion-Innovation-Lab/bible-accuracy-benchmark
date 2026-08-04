"""Benchmark dataset: the public sampling spec and the per-refresh sampler.

No verse text lives here or in the committed spec — only references (USFM),
version IDs, and one-way truth hashes.

ONE reference list is drawn per benchmark version and asked of EVERY translation,
so every column of the board answers the same questions. The list is drawn in the
`eng` versification scheme and translated into each edition's own scheme before
being asked, because the same reference is not the same verse across schemes (an
uncorrected PSA.23.1 is a different psalm in three of the eighteen translations —
see versification.py). Where an edition doesn't carry the resolved reference, the
item is dropped; that absence belongs to the Hallucination dimension.

There is no per-language anything. Counts are global, the draw is global, and a
translation is a translation.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import versification
from .normalize import normalize
from .usfm import VerseRef, canon_of
from .yv_client import BibleClient

# The scheme every reference is drawn and stored in. Editions get it translated.
REFERENCE_SCHEME = "eng"


@dataclass(frozen=True)
class Reference:
    """One question, before it is pointed at any particular edition."""
    usfm: str      # in REFERENCE_SCHEME
    tier: str


def draw_references(
    spec: dict, seed: str, famous: list[str], obscure: list[str], *,
    books: list[str], counts_scale: float = 1.0, probe: set[str] | None = None,
) -> list[Reference]:
    """The global reference list: famous + obscure (curated) + body (drawn).

    Body is exactly one verse per book, over ``books`` — the union of every book
    ANY tested edition carries, which is what makes the tier version-driven
    rather than canon-driven. Every book contributes equally regardless of
    length, and every edition is asked the same verse of each book it has.

    The union matters for more than the deuterocanon. Daniel and Esther exist in
    Hebrew and Greek forms under different codes (`DAN`/`DAG`, `EST`/`ESG`), and
    only 64 of the Protestant 66 are in all 18 editions for exactly that reason.
    Carrying both forms in the list means every edition is asked a Daniel and an
    Esther — each gets the one it actually has, and drops the other.

    Deterministic given (seed, books). Chapter and verse bounds come from the
    vendored `eng` versification table, which numbers all 85 books in the union,
    so the draw itself needs no API call.
    """
    probe = probe or set()

    def scale(xs: list) -> list:
        """Trim a list for pilot runs; full runs pass everything through."""
        return xs[: max(1, round(len(xs) * counts_scale))] if counts_scale < 1 else xs

    refs = [Reference(u, "famous") for u in scale(famous)]
    refs += [Reference(u, "obscure") for u in scale(obscure)]

    rng = random.Random(int(hashlib.sha256(f"{seed}:body".encode()).hexdigest(), 16) % (2**32))
    taken = {r.usfm for r in refs}
    for book in scale(sorted(books)):
        chapters = versification.chapter_count(book, REFERENCE_SCHEME)
        if not chapters:
            continue
        # A handful of attempts is plenty: the only rejections are a collision
        # with a curated reference or a known textual-variant probe verse.
        for _ in range(24):
            chapter = rng.randint(1, chapters)
            verses = versification.max_verses(book, chapter, REFERENCE_SCHEME)
            if not verses:
                continue
            usfm = f"{book}.{chapter}.{rng.randint(1, verses)}"
            if usfm not in taken and usfm not in probe:
                taken.add(usfm)
                refs.append(Reference(usfm, "body"))
                break
    return refs


@dataclass(frozen=True)
class BenchmarkItem:
    id: str
    track: str
    language_tag: str
    language_name: str
    version_id: int
    version_abbrev: str
    # The reference AS THIS EDITION NUMBERS IT — what gets asked and graded.
    usfm: str
    # The same reference in REFERENCE_SCHEME, identical across every edition
    # asked. Two editions numbering a verse differently share this, which is what
    # makes "the same question" comparable across translations.
    source_usfm: str
    tier: str
    template_id: str
    distractor_version_ids: list[int] = field(default_factory=list)
    truth_sha256: str = ""
    # Which canon slice this verse's book is reported under — protestant (the 66
    # every edition shares), catholic, orthodox. A *label*, recorded at sampling
    # time so a run can be re-scored without re-deriving it. `tier` means
    # difficulty and nothing else; canon is a separate axis.
    canon: str = "protestant"

    def to_json(self) -> dict:
        return asdict(self)


def load_spec(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def load_reference_list(path: str | Path) -> list[str]:
    """USFM references from a committed .jsonl list (famous, obscure)."""
    return [
        json.loads(line)["usfm"]
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]


class DatasetSampler:
    """Draws a concrete benchmark item set for one refresh.

    Deterministic given (spec, seed, current API content). Fetches chapters to
    validate verses; the client's in-memory cache means neighbor lookups during
    scoring reuse the same fetches.
    """

    def __init__(self, client: BibleClient, spec: dict, spec_dir: Path):
        self._client = client
        self._spec = spec
        self._spec_dir = spec_dir
        self._famous = load_reference_list(spec["famous_file"])
        self._obscure = load_reference_list(spec["obscure_file"])
        self._probe = set(spec.get("probe_set", {}).get("usfms", []))

    async def _valid_verses(self, version_id: int, chapter_usfm: str) -> list[str]:
        """Single-verse (non-merged) USFMs of a chapter, minus probe verses."""
        verses = await self._client.chapter_verses(version_id, chapter_usfm)
        return sorted(
            (u for u in verses if u not in self._probe),
            key=lambda u: VerseRef.parse(u).verse,
        )

    async def _chapters_by_book(self, version_id: int) -> dict[str, list[str]]:
        """{book_usfm: [chapter_usfm, ...]} for whatever books THIS edition has.

        Canon is a property of the version, so there is no canon filter here. A
        Catholic edition offers Tobit; a Protestant one doesn't; both are answered
        by the same code path.
        """
        meta = await self._client.version(version_id)
        out: dict[str, list[str]] = {}
        for b in meta.get("books", []):
            book = b.get("usfm")
            if not book:
                continue
            chapters = [
                c["usfm"]
                for c in b.get("chapters", [])
                if c.get("canonical", True)
                and "." in c.get("usfm", "")
                and "INTRO" not in c["usfm"]
            ]
            if chapters:
                out[book] = chapters
        return out

    async def _make_item(
        self, lang: str, lang_name: str, version_id: int, version_abbrev: str, *,
        source_usfm: str, usfm: str, tier: str, distractors: list[int],
    ) -> BenchmarkItem | None:
        """One item, or None when this edition doesn't carry the reference.

        The edition's own verse list is the authority — the versification scheme
        says how an edition WOULD number a verse, not whether it has it.
        """
        span = await self._client.verse(version_id, usfm)
        if span is None:
            return None
        digest = hashlib.sha256(normalize(span.text, "loose").encode()).hexdigest()
        return BenchmarkItem(
            id=f"s-{lang}-{version_id}-{usfm}",
            track="simple", language_tag=lang, language_name=lang_name,
            version_id=version_id, version_abbrev=version_abbrev, usfm=usfm,
            source_usfm=source_usfm, tier=tier, template_id="quote_exact",
            distractor_version_ids=[d for d in distractors if d != version_id],
            truth_sha256=digest,
            canon=canon_of(VerseRef.parse(usfm).book),
        )

    async def sample(self, seed: str, counts_scale: float = 1.0) -> list[BenchmarkItem]:
        """Every (reference, translation) pair the Direct Quotation track tests.

        One reference list, asked of every translation. The list is drawn in the
        `eng` versification scheme and translated into each edition's own scheme
        before it is asked, because the same reference is not the same verse
        across schemes (see versification.py). Where an edition doesn't carry the
        resolved reference the item is dropped — that absence is Hallucination
        Resistance's subject, not this dimension's.

        No language branch anywhere: a translation is a translation.
        """
        # The book union, derived from the editions themselves — the same
        # principle as v0.4's canon work: whatever a version has, it can be asked
        # for, and no book list lives in this codebase.
        by_version: dict[int, tuple[str, str, str]] = {}
        books: set[str] = set()
        for lang_cfg in self._spec["languages"].values():
            for vid in lang_cfg.get("versions") or [lang_cfg["primary"]]:
                meta = await self._client.version(vid)
                by_version[vid] = (
                    meta.get("vrs") or REFERENCE_SCHEME,
                    (meta.get("abbreviation") or "").upper(),
                    "",
                )
                books |= set(await self._client.version_books(vid))

        refs = draw_references(self._spec, seed, self._famous, self._obscure,
                               books=sorted(books), counts_scale=counts_scale,
                               probe=self._probe)
        items: list[BenchmarkItem] = []
        for lang, lang_cfg in self._spec["languages"].items():
            lang_name = lang_cfg["name"]
            distractors = self._spec.get("distractor_pools", {}).get(lang, [])
            version_ids = lang_cfg.get("versions") or [lang_cfg["primary"]]
            for vid in version_ids:
                scheme, abbrev, _ = by_version[vid]
                for ref in refs:
                    # THE shared path: correct the reference for this edition's
                    # versification, then ask this edition whether it has it.
                    target = versification.translate(ref.usfm, REFERENCE_SCHEME, scheme)
                    item = await self._make_item(
                        lang, lang_name, vid, abbrev,
                        source_usfm=ref.usfm, usfm=target, tier=ref.tier,
                        distractors=distractors,
                    )
                    if item:
                        items.append(item)
                self._client.release_version(vid)
        return items
