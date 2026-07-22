"""Disk-cache behavior for BibleClient, with the network stubbed — no real API
and no scripture. Verifies write-through, read-back, and that a warm cache
serves without any further network calls."""

import json

import pytest

from bible_bench.config import BibleApiConfig
from bible_bench.yv_client import BibleClient, CacheMissError

# Minimal fake chapter.json HTML with one verse span (invented text).
_HTML = (
    '<div><span class="verse" data-usfm="GEN.1.1">'
    '<span class="content">fake opening line of the test book</span></span></div>'
)
_VERSION_JSON = {
    "books": [{"usfm": "GEN", "human": "Genesis",
               "chapters": [{"usfm": "GEN.1", "canonical": True}]}]
}


class _StubClient(BibleClient):
    """BibleClient whose _get is stubbed to count calls and return fakes."""

    def __init__(self, cache_dir, offline=False):
        super().__init__(BibleApiConfig(base_url="x", headers={}),
                         cache_dir=cache_dir, offline=offline)
        self.calls = 0

    async def _get(self, endpoint, params):  # type: ignore[override]
        self.calls += 1
        if endpoint == "version.json":
            return _VERSION_JSON
        if endpoint == "chapter.json":
            return {"content": _HTML}
        raise AssertionError(endpoint)


async def test_write_through_and_warm_read(tmp_path):
    c1 = _StubClient(tmp_path)
    spans = await c1.chapter(111, "GEN.1")
    assert spans["GEN.1.1"].text == "fake opening line of the test book"
    assert c1.calls == 1
    await c1.aclose()

    # File written under the cache dir.
    assert (tmp_path / "v111" / "GEN.1.json").exists()

    # A fresh client with the same cache dir serves from disk — zero network.
    c2 = _StubClient(tmp_path)
    spans2 = await c2.chapter(111, "GEN.1")
    assert spans2["GEN.1.1"].text == "fake opening line of the test book"
    assert c2.calls == 0
    await c2.aclose()


async def test_no_cache_dir_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _StubClient(None)
    await c.chapter(111, "GEN.1")
    await c.aclose()
    assert list(tmp_path.iterdir()) == []  # default path never touches disk


async def test_chapter_usfms_enumeration(tmp_path):
    c = _StubClient(tmp_path)
    assert await c.chapter_usfms(111) == ["GEN.1"]
    await c.aclose()


async def test_disk_roundtrip_preserves_spans(tmp_path):
    c1 = _StubClient(tmp_path)
    await c1.chapter(111, "GEN.1")
    await c1.aclose()
    raw = json.loads((tmp_path / "v111" / "GEN.1.json").read_text())
    assert raw == [["GEN.1.1", 1, "fake opening line of the test book", "GEN.1.1"]]


@pytest.mark.parametrize("cache", [True, False])
async def test_verse_lookup_works_both_modes(tmp_path, cache):
    c = _StubClient(tmp_path if cache else None)
    v = await c.verse(111, "GEN.1.1")
    assert v is not None and v.text.startswith("fake opening")
    await c.aclose()


async def test_offline_requires_cache_dir():
    with pytest.raises(CacheMissError):
        _StubClient(None, offline=True)


async def test_offline_miss_raises_not_fetches(tmp_path):
    # Nothing prefetched → offline reads must fail, never hit the network.
    c = _StubClient(tmp_path, offline=True)
    with pytest.raises(CacheMissError):
        await c.chapter(111, "GEN.1")
    with pytest.raises(CacheMissError):
        await c.version(111)
    assert c.calls == 0
    await c.aclose()


async def test_offline_absent_chapter_returns_empty_not_error(tmp_path):
    # Prefetch a version whose version.json lists only GEN.1 (so GEN.2 is
    # genuinely absent, like Septuagint Psalm numbering). Offline lookups of
    # the absent chapter must return {} (→ verse None → skipped), not raise.
    warm = _StubClient(tmp_path)
    await warm.version(111)           # caches version.json (only GEN.1)
    await warm.chapter(111, "GEN.1")  # caches the one real chapter
    await warm.aclose()

    c = _StubClient(tmp_path, offline=True)
    assert await c.chapter(111, "GEN.2") == {}      # absent in version → empty
    assert await c.verse(111, "GEN.2.5") is None    # → sampler skips it
    with pytest.raises(CacheMissError):
        await c.chapter(999, "GEN.1")               # unknown version → still errors
    assert c.calls == 0
    await c.aclose()


async def test_offline_serves_prefetched(tmp_path):
    # Prefetch online, then read offline with zero network.
    warm = _StubClient(tmp_path)
    await warm.chapter(111, "GEN.1")
    await warm.version(111)
    await warm.aclose()

    c = _StubClient(tmp_path, offline=True)
    spans = await c.chapter(111, "GEN.1")
    assert spans["GEN.1.1"].text.startswith("fake opening")
    assert c.calls == 0
    await c.aclose()
