"""Hash-pinned live-API regression tests.

Skipped automatically when Bible API credentials are absent (e.g. in public
CI). With credentials, these verify the full client → HTML parsing →
normalization path against known digests of already-public verse text. No
verse text is committed — only one-way SHA-256 digests.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from bible_bench.normalize import normalize

pytestmark = pytest.mark.live

load_dotenv()
_HAVE_CREDS = bool(os.environ.get("YV_API_BASE_URL") and os.environ.get("YV_API_HEADERS"))
if not _HAVE_CREDS:
    pytest.skip("Bible API credentials not configured", allow_module_level=True)

CANARIES = json.loads((Path(__file__).parent / "canaries.json").read_text())


@pytest.fixture(scope="module")
async def client():
    from bible_bench.config import load_bible_api_config
    from bible_bench.yv_client import BibleClient

    c = BibleClient(load_bible_api_config())
    yield c
    await c.aclose()


@pytest.mark.parametrize(
    "canary", CANARIES, ids=[f"{c['version_id']}-{c['usfm']}" for c in CANARIES]
)
async def test_canary_digest(client, canary):
    span = await client.verse(canary["version_id"], canary["usfm"])
    assert span is not None, "canary verse missing or merged upstream"
    digest = hashlib.sha256(normalize(span.text, "loose").encode()).hexdigest()
    assert digest == canary["sha256_loose"], (
        f"Ground-truth drift or parsing regression for "
        f"{canary['version_id']} {canary['usfm']}"
    )


async def test_client_writes_nothing_to_disk(client, tmp_path, monkeypatch):
    """Verse text must exist in memory only: exercising the client must not
    create a single file anywhere in the working directory."""
    monkeypatch.chdir(tmp_path)
    await client.verse(111, "GEN.1.1")
    await client.chapter_verses(111, "GEN.1")
    await client.human_reference(111, "GEN.1.1")
    assert list(tmp_path.iterdir()) == []


async def test_localized_human_reference(client):
    # Spanish version renders its own book name, not English ("SAN JUAN" in
    # the version metadata, title-cased for prompt text).
    ref = await client.human_reference(149, "JHN.3.16")
    assert ref == "San Juan 3:16"


_DATASET_DIR = Path(__file__).parent.parent / "dataset"


def test_hallucination_takes_its_translations_from_the_spec():
    """Hallucination Resistance is scored per translation, and its translations
    come from spec-v1.json — the same list Direct Quotation uses. A version or
    abbreviation hand-written here would be a second source of truth that could
    disagree with the spec, which is exactly how Arabic ended up labelled with
    the wrong translation's abbreviation."""
    blocks = json.loads((_DATASET_DIR / "hallucination-v1.json").read_text())["languages"]
    strays = {
        lang: [k for k in ("version_id", "version_abbrev", "template") if k in block]
        for lang, block in blocks.items()
    }
    assert not any(strays.values()), f"per-translation config leaked back in: {strays}"


# A canary that checked hand-written version_abbrev values against the API lived
# here. Its only subject was topics-v1.json, deleted with the Scripture in Answers
# dimension; hallucination-v1.json hand-writes no abbreviations, and the direct-quote
# track reads them from the API rather than a file, so the drift it caught (Arabic
# labelled "AVD" while pointing at the New Arabic Version) has no route back in.
