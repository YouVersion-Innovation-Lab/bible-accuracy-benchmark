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
