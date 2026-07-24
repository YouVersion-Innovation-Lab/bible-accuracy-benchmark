"""Benchmark dataset: the public sampling spec and the per-refresh sampler.

No verse text lives here or in the committed spec — only references (USFM),
version IDs, and one-way truth hashes. The sampler draws a concrete item set
for one leaderboard refresh from the spec plus a seed, validating every
(version, verse) pair against the live API and dropping merged/absent verses.
The resulting item list is published with the run so results are auditable.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .normalize import normalize
from .usfm import CANON_ORDER, SINGLE_CHAPTER_BOOKS, VerseRef
from .yv_client import BibleClient

# Curated obscure pools (chapters heavy on names/numbers where models drift).
_GENEALOGY_CHAPTERS = ["GEN.5", "GEN.10", "GEN.36", "1CH.1", "1CH.2", "1CH.6", "MAT.1", "LUK.3"]
_CENSUS_CHAPTERS = ["NUM.1", "NUM.2", "NUM.7", "NUM.26", "EZR.2", "NEH.7"]
_NUMBER_HEAVY_CHAPTERS = ["EXO.38", "1KI.7", "EZK.48", "JOS.15", "JOS.19"]
_MINOR_PROPHET_CHAPTERS = ["NAM.3", "OBA.1", "HAB.3", "ZEP.2", "HAG.1", "MAL.1", "JOL.2", "AMO.5"]


@dataclass(frozen=True)
class BenchmarkItem:
    id: str
    track: str
    language_tag: str
    language_name: str
    version_id: int
    version_abbrev: str
    usfm: str
    tier: str
    template_id: str
    distractor_version_ids: list[int] = field(default_factory=list)
    truth_sha256: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def load_spec(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def load_famous(spec: dict, spec_dir: Path) -> list[str]:
    famous_path = spec_dir.parent / spec["famous_file"]
    if not famous_path.is_absolute():
        famous_path = Path(spec["famous_file"])
    usfms = []
    for line in famous_path.read_text().splitlines():
        line = line.strip()
        if line:
            usfms.append(json.loads(line)["usfm"])
    return usfms


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
        self._famous = load_famous(spec, spec_dir)
        self._probe = set(spec.get("probe_set", {}).get("usfms", []))

    async def _valid_verses(self, version_id: int, chapter_usfm: str) -> list[str]:
        """Single-verse (non-merged) USFMs of a chapter, minus probe verses."""
        verses = await self._client.chapter_verses(version_id, chapter_usfm)
        return sorted(
            (u for u in verses if u not in self._probe),
            key=lambda u: VerseRef.parse(u).verse,
        )

    async def _canonical_chapters(self, version_id: int) -> dict[str, list[str]]:
        """{book_usfm: [chapter_usfm, ...]} for canonical chapters only."""
        meta = await self._client.version(version_id)
        out: dict[str, list[str]] = {}
        for b in meta.get("books", []):
            book = b.get("usfm")
            if book not in CANON_ORDER:
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
        self, track: str, lang: str, lang_name: str, version_id: int,
        version_abbrev: str, usfm: str, tier: str, template_id: str,
        distractors: list[int],
    ) -> BenchmarkItem | None:
        span = await self._client.verse(version_id, usfm)
        if span is None:
            return None
        digest = hashlib.sha256(normalize(span.text, "loose").encode()).hexdigest()
        return BenchmarkItem(
            id=f"{track[0]}-{lang}-{version_id}-{usfm}",
            track=track, language_tag=lang, language_name=lang_name,
            version_id=version_id, version_abbrev=version_abbrev, usfm=usfm,
            tier=tier, template_id=template_id,
            distractor_version_ids=[d for d in distractors if d != version_id],
            truth_sha256=digest,
        )

    async def _sample_from_chapter_pool(
        self, rng: random.Random, version_id: int, chapter_pool: list[str], count: int,
        chosen: set[str],
    ) -> list[str]:
        """Pick ``count`` distinct valid verses drawn from ``chapter_pool``."""
        picked: list[str] = []
        pool = list(chapter_pool)
        rng.shuffle(pool)
        attempts = 0
        while len(picked) < count and attempts < count * 8 + 40 and pool:
            chapter = pool[attempts % len(pool)]
            attempts += 1
            verses = await self._valid_verses(version_id, chapter)
            candidates = [u for u in verses if u not in chosen]
            if not candidates:
                continue
            u = rng.choice(candidates)
            chosen.add(u)
            picked.append(u)
        return picked

    async def sample_language(
        self, rng: random.Random, lang: str, lang_cfg: dict, counts_scale: float = 1.0,
    ) -> list[BenchmarkItem]:
        version_id = lang_cfg["primary"]
        lang_name = lang_cfg["name"]
        distractors = self._spec.get("distractor_pools", {}).get(lang, [version_id])
        chapters_by_book = await self._canonical_chapters(version_id)
        chosen: set[str] = set()
        items: list[BenchmarkItem] = []
        is_eng = lang == "eng"

        def n(tier: str) -> int:
            key = "english_count" if is_eng else "other_language_count"
            return max(0, round(self._spec["tiers"][tier][key] * counts_scale))

        # Per-book floor scales with counts_scale so small pilots stay small;
        # at scale 1.0 this is the spec's min_verses_per_book (2).
        spec_floor = self._spec["tiers"]["body"]["min_verses_per_book"]
        if counts_scale >= 1:
            min_per_book = max(1, round(spec_floor * counts_scale))
        else:
            min_per_book = 1 if counts_scale >= 0.25 else 0

        # Verses are sampled/validated against the primary version, then tested
        # in every version listed for the language (absent verses drop out).
        version_ids = lang_cfg.get("versions", [version_id])

        async def add(usfm: str, tier: str, template_id: str) -> None:
            for vid in version_ids:
                v_meta = await self._client.version(vid)
                item = await self._make_item(
                    "simple", lang, lang_name, vid, v_meta.get("abbreviation", "").upper(),
                    usfm, tier, template_id, distractors,
                )
                if item:
                    items.append(item)

        # famous — English uses all IDs across its version list; others sample a subset
        famous = list(self._famous)
        rng.shuffle(famous)
        famous = famous[: n("famous")]
        for usfm in famous:
            if usfm in chosen:
                continue
            chosen.add(usfm)
            await add(usfm, "famous", "quote_exact")

        # body — stratified: ≥min_per_book verses/book, remainder weighted by
        # chapter count, hard-capped at body_total.
        body_total = n("body")
        books = list(chapters_by_book)
        base = {b: min(min_per_book, len(chapters_by_book[b])) for b in books}
        # Trim floor allocation down to body_total when the floor alone exceeds it.
        while sum(base.values()) > body_total and any(v > 0 for v in base.values()):
            for b in rng.sample(books, len(books)):
                if base[b] > 0:
                    base[b] -= 1
                    if sum(base.values()) <= body_total:
                        break
        remaining = max(0, body_total - sum(base.values()))
        weights = [len(chapters_by_book[b]) for b in books]
        for b in rng.choices(books, weights=weights, k=remaining) if remaining else []:
            base[b] += 1
        for b in books:
            if base[b] <= 0:
                continue
            picked = await self._sample_from_chapter_pool(
                rng, version_id, chapters_by_book[b], base[b], chosen
            )
            for usfm in picked:
                await add(usfm, "body", "quote_exact")

        # obscure — curated pools
        obscure_pool = [
            c for c in (_GENEALOGY_CHAPTERS + _CENSUS_CHAPTERS + _NUMBER_HEAVY_CHAPTERS
                        + _MINOR_PROPHET_CHAPTERS + ["PSA.119"])
            if c.split(".")[0] in chapters_by_book
        ]
        for usfm in await self._sample_from_chapter_pool(
            rng, version_id, obscure_pool, n("obscure"), chosen
        ):
            await add(usfm, "obscure", "quote_exact")

        # edge — single-chapter books + final verses of chapters
        edge_chapters = [
            chapters_by_book[b][0] for b in SINGLE_CHAPTER_BOOKS if b in chapters_by_book
        ]
        edge_chapters += [
            rng.choice(chapters_by_book[b]) for b in rng.sample(books, min(len(books), 20))
        ]
        edge_verses: list[str] = []
        for chapter in edge_chapters:
            verses = await self._valid_verses(version_id, chapter)
            if verses and verses[-1] not in chosen:
                edge_verses.append(verses[-1])
        rng.shuffle(edge_verses)
        for usfm in edge_verses[: n("edge")]:
            chosen.add(usfm)
            await add(usfm, "edge", "quote_exact")

        # deuterocanon — the extra (apocryphal) books, sampled ONLY from versions
        # in this language whose metadata actually carries them (e.g. a Catholic
        # Bible like NABRE). Protestant versions don't contain these books, so
        # only the version that has them is tested on them.
        deutero = self._spec.get("deuterocanon")
        if deutero:
            d_books = set(deutero.get("books", []))
            count_key = "english_count" if is_eng else "other_language_count"
            d_count = max(0, round(deutero[count_key] * counts_scale))
            for vid in version_ids if d_count else []:
                vmeta = await self._client.version(vid)
                d_chapters = [
                    c["usfm"]
                    for b in vmeta.get("books", [])
                    if b.get("usfm") in d_books
                    for c in b.get("chapters", [])
                    if c.get("canonical", True)
                    and "." in c.get("usfm", "")
                    and "INTRO" not in c["usfm"]
                ]
                if not d_chapters:
                    continue
                d_chosen: set[str] = set()
                for usfm in await self._sample_from_chapter_pool(
                    rng, vid, d_chapters, d_count, d_chosen
                ):
                    item = await self._make_item(
                        "simple", lang, lang_name, vid,
                        vmeta.get("abbreviation", "").upper(),
                        usfm, "deuterocanon", "quote_exact", distractors,
                    )
                    if item:
                        items.append(item)

        return items

    async def sample(self, seed: str, counts_scale: float = 1.0) -> list[BenchmarkItem]:
        items: list[BenchmarkItem] = []
        for lang, lang_cfg in self._spec["languages"].items():
            # Per-language seed derivation keeps languages independent and stable.
            lang_seed = int(hashlib.sha256(f"{seed}:{lang}".encode()).hexdigest(), 16) % (2**32)
            rng = random.Random(lang_seed)
            items.extend(await self.sample_language(rng, lang, lang_cfg, counts_scale))
        return items
