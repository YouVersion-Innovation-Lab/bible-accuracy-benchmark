"""Async client for the Bible text API (ground-truth verse text).

Default rule: verse text is fetched at runtime and held in process memory only
— with ``cache_dir=None`` the client writes nothing to disk (a CI test asserts
this). Passing a ``cache_dir`` turns on an opt-in local disk cache for
operators running evaluations on their own machine (see the ``prefetch`` CLI
command); that directory must stay gitignored and is never used by the deployed
website. No Bible text is ever committed to the repo.

Endpoint shapes (JSON envelope ``response.data``):

- ``versions.json?language_tag=<iso639-3>&type=all`` → ``{versions: [{id, ...}]}``
- ``version.json?id=<vid>`` → version metadata incl. ``books[].chapters[]``
  (usfm codes, canonical flags) and localized book names
- ``chapter.json?id=<vid>&reference=<BOOK.CH>`` → ``{content: <html>}`` where
  the HTML carries per-verse ``<span class="verse" data-usfm="GEN.1.1">`` spans
  whose ``<span class="content">`` children hold the text. Footnotes/cross-refs
  live under ``.note`` and are stripped. Merged printed spans carry
  ``+``-joined data-usfm values (e.g. ``PSA.136.4+PSA.136.5``).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .config import BibleApiConfig
from .usfm import CANON_ORDER, SINGLE_CHAPTER_BOOKS, VerseRef, is_standard_verse_usfm

_WS = re.compile(r"\s+")

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 5


class BibleApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class VersionMeta:
    id: int
    abbreviation: str
    local_abbreviation: str
    title: str
    language_tag: str


@dataclass(frozen=True)
class VerseSpan:
    """One printed span of verse text. ``anchor`` is the first verse's usfm;
    ``extent`` > 1 means a merged span covering several verse numbers."""

    anchor: str
    extent: int
    text: str
    raw_usfm: str  # original, possibly '+'-joined identifier


def parse_spans(content_html: str) -> list[VerseSpan]:
    """(anchor, extent, text) per printed span, in document order.

    Ported from patton's build-verse-db.py: a verse split across paragraphs
    (same data-usfm on several spans) is concatenated; footnotes stripped;
    merged blocks keep their '+'-joined identity anchored at the first verse.
    """
    soup = BeautifulSoup(content_html or "", "lxml")
    acc: dict[str, list[str]] = {}
    order: list[str] = []
    for vspan in soup.select("span.verse[data-usfm]"):
        usfm = (vspan.get("data-usfm") or "").strip()
        if not usfm:
            continue
        for note in vspan.select(".note"):
            note.extract()
        text = " ".join(c.get_text(" ", strip=True) for c in vspan.select("span.content"))
        text = _WS.sub(" ", text).strip()
        if not text:
            continue
        if usfm not in acc:
            acc[usfm] = []
            order.append(usfm)
        acc[usfm].append(text)

    out: list[VerseSpan] = []
    for usfm in order:
        parts = [p.strip() for p in usfm.split("+") if p.strip()]
        anchor = parts[0]
        extent = len(parts)
        try:
            a_bk, a_ch, a_v = anchor.split(".")
            z_bk, z_ch, z_v = parts[-1].split(".")
            if a_bk == z_bk and a_ch == z_ch and int(z_v) >= int(a_v):
                extent = int(z_v) - int(a_v) + 1
        except ValueError:
            pass
        out.append(
            VerseSpan(
                anchor=anchor,
                extent=extent,
                text=_WS.sub(" ", " ".join(acc[usfm])).strip(),
                raw_usfm=usfm,
            )
        )
    return out


class BibleClient:
    """Async Bible API client with an in-memory chapter cache and an optional
    on-disk cache.

    Chapter fetches are the cache unit (scoring needs same-chapter neighbor
    verses anyway). Per-key locks prevent duplicate concurrent fetches; a
    global semaphore caps API concurrency as a politeness ceiling.

    ``cache_dir`` enables a read-through / write-through local disk cache of
    chapter text and version metadata. This is an opt-in convenience for
    operators running evaluations on their own machine (see the ``prefetch``
    CLI command) — it is never used by the deployed website and the directory
    must stay gitignored. With ``cache_dir=None`` (the default) the client
    writes nothing to disk.
    """

    def __init__(self, cfg: BibleApiConfig, cache_dir: str | Path | None = None):
        self._cfg = cfg
        self._http = httpx.AsyncClient(
            base_url=cfg.base_url,
            headers=cfg.headers,
            timeout=cfg.timeout_seconds,
        )
        self._sem = asyncio.Semaphore(cfg.max_concurrency)
        # (version_id, chapter_usfm) -> {anchor_usfm: VerseSpan}
        self._chapters: dict[tuple[int, str], dict[str, VerseSpan]] = {}
        # version_id -> version.json data
        self._versions: dict[int, dict] = {}
        self._locks: dict[object, asyncio.Lock] = {}
        self._cache_dir = Path(cache_dir) if cache_dir else None

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- on-disk cache (opt-in) ------------------------------------------
    def _chapter_path(self, version_id: int, chapter_usfm: str) -> Path:
        return self._cache_dir / f"v{version_id}" / f"{chapter_usfm}.json"

    def _version_path(self, version_id: int) -> Path:
        return self._cache_dir / f"v{version_id}" / "version.json"

    def _load_chapter_disk(self, version_id: int, chapter_usfm: str) -> dict[str, VerseSpan] | None:
        p = self._chapter_path(version_id, chapter_usfm)
        if not p.exists():
            return None
        rows = json.loads(p.read_text(encoding="utf-8"))
        spans = {r[0]: VerseSpan(anchor=r[0], extent=r[1], text=r[2], raw_usfm=r[3]) for r in rows}
        return spans

    def _save_chapter_disk(self, version_id: int, chapter_usfm: str,
                           spans: dict[str, VerseSpan]) -> None:
        p = self._chapter_path(version_id, chapter_usfm)
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = [[s.anchor, s.extent, s.text, s.raw_usfm] for s in spans.values()]
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def _lock(self, key: object) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _get(self, endpoint: str, params: dict) -> dict:
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._sem:
                    resp = await self._http.get(endpoint, params=params)
                if resp.status_code in _RETRYABLE_STATUSES:
                    raise BibleApiError(
                        f"{endpoint} -> HTTP {resp.status_code}", status=resp.status_code
                    )
                if resp.status_code != 200:
                    raise BibleApiError(
                        f"Bible API {endpoint} {params} -> HTTP {resp.status_code}",
                        status=resp.status_code,
                    )
                data = resp.json().get("response", {}).get("data")
                if data is None:
                    raise BibleApiError(f"Bible API {endpoint} {params} -> missing data")
                return data
            except (httpx.TransportError, BibleApiError) as e:
                last_err = e
                non_retryable = (
                    isinstance(e, BibleApiError)
                    and e.status is not None
                    and e.status not in _RETRYABLE_STATUSES
                )
                if non_retryable:
                    raise
                await asyncio.sleep((2**attempt) + random.random())
        raise BibleApiError(
            f"Bible API {endpoint} failed after {_MAX_RETRIES} retries"
        ) from last_err

    async def versions(self, language_tag: str) -> list[VersionMeta]:
        data = await self._get(
            "versions.json", {"language_tag": language_tag, "type": "all"}
        )
        out = []
        for v in data.get("versions", []):
            out.append(
                VersionMeta(
                    id=v["id"],
                    abbreviation=v.get("abbreviation", ""),
                    local_abbreviation=v.get("local_abbreviation", v.get("abbreviation", "")),
                    title=v.get("title", v.get("local_title", "")),
                    language_tag=language_tag,
                )
            )
        return out

    async def version(self, version_id: int) -> dict:
        async with self._lock(("version", version_id)):
            if version_id not in self._versions:
                if self._cache_dir and (p := self._version_path(version_id)).exists():
                    self._versions[version_id] = json.loads(p.read_text(encoding="utf-8"))
                else:
                    data = await self._get("version.json", {"id": version_id})
                    self._versions[version_id] = data
                    if self._cache_dir:
                        p = self._version_path(version_id)
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self._versions[version_id]

    async def chapter(self, version_id: int, chapter_usfm: str) -> dict[str, VerseSpan]:
        """All printed spans of a chapter, keyed by anchor usfm. Cached in
        memory, and on disk when a cache dir is configured."""
        key = (version_id, chapter_usfm.upper())
        async with self._lock(key):
            if key not in self._chapters:
                if self._cache_dir and (disk := self._load_chapter_disk(*key)) is not None:
                    self._chapters[key] = disk
                else:
                    try:
                        data = await self._get(
                            "chapter.json", {"id": version_id, "reference": key[1]}
                        )
                        spans = parse_spans(data.get("content", ""))
                        self._chapters[key] = {s.anchor: s for s in spans}
                    except BibleApiError as e:
                        # A chapter absent from this version (e.g. an NT-only
                        # edition, or a differing canon) returns 404 — treat it
                        # as "no verses here" rather than a fatal error.
                        if e.status == 404:
                            self._chapters[key] = {}
                        else:
                            raise
                    if self._cache_dir:
                        self._save_chapter_disk(*key, self._chapters[key])
        return self._chapters[key]

    async def chapter_usfms(self, version_id: int) -> list[str]:
        """Every canonical chapter USFM in a version (from version.json).
        Used by prefetch to enumerate the whole Bible for a version."""
        meta = await self.version(version_id)
        out: list[str] = []
        for b in meta.get("books", []):
            if b.get("usfm") not in CANON_ORDER:
                continue
            for c in b.get("chapters", []):
                cu = c.get("usfm", "")
                if c.get("canonical", True) and "." in cu and "INTRO" not in cu.upper():
                    out.append(cu)
        return out

    async def verse(self, version_id: int, usfm: str) -> VerseSpan | None:
        """Text of a single verse, or None if absent in this version.

        Returns the span only when it is a clean single-verse span; merged
        printed spans (extent > 1) return None — the benchmark excludes them
        at sampling time, and scoring must never attribute merged text to one
        verse.
        """
        ref = VerseRef.parse(usfm)
        spans = await self.chapter(version_id, ref.chapter_usfm)
        span = spans.get(ref.usfm)
        if span is None or span.extent != 1:
            return None
        return span

    async def chapter_verses(self, version_id: int, chapter_usfm: str) -> dict[str, str]:
        """Single-verse spans of a chapter as {usfm: text}.

        Merged spans (extent > 1) and non-standard anchors (split-chapter or
        subdivided identifiers like ``PSA.106_1.1``) are skipped."""
        spans = await self.chapter(version_id, chapter_usfm)
        return {
            s.anchor: s.text
            for s in spans.values()
            if s.extent == 1 and is_standard_verse_usfm(s.anchor)
        }

    async def human_reference(self, version_id: int, usfm: str) -> str:
        """Localized human-readable reference using the version's own book
        names (e.g. 'Juan 3:16' for a Spanish version)."""
        ref = VerseRef.parse(usfm)
        meta = await self.version(version_id)
        name = None
        for b in meta.get("books", []):
            if b.get("usfm") == ref.book:
                name = b.get("human") or b.get("human_long")
                break
        if not name:
            return ref.english_reference()
        if name.isupper():
            # Some versions store display names in ALL CAPS ("SAN JUAN");
            # title-case for natural prompt text.
            name = name.title()
        if ref.book in SINGLE_CHAPTER_BOOKS:
            return f"{name} {ref.verse}"
        return f"{name} {ref.chapter}:{ref.verse}"
