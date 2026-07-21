"""Regenerate tests/canaries.json — hash-pinned live-API regression anchors.

Each canary is (version_id, usfm, sha256 of the loose-normalized verse text).
A digest of already-public text commits no text to the repo, but any upstream
edition change, HTML-parsing regression, or normalization change will trip the
live test suite. Run by maintainers with API credentials:

    python scripts/generate_canaries.py
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bible_bench.config import load_bible_api_config  # noqa: E402
from bible_bench.normalize import normalize  # noqa: E402
from bible_bench.yv_client import BibleClient  # noqa: E402

# Spread across canon position, version, language, and script.
CANARIES: list[tuple[int, str]] = [
    (111, "GEN.1.1"),      # NIV, canon start
    (111, "JHN.3.16"),     # NIV, most-quoted verse
    (111, "PSA.23.1"),     # NIV, small-caps divine name (nd span)
    (111, "EST.8.9"),      # NIV, longest verse
    (111, "REV.22.21"),    # NIV, canon end
    (1, "JHN.3.16"),       # KJV
    (1, "PSA.119.105"),    # KJV, Psalm 119 interior
    (116, "ROM.8.28"),     # NLT
    (116, "PHP.4.13"),     # NLT
    (149, "JHN.3.16"),     # RVR1960 (Spanish)
    (129, "JHN.3.16"),     # NVI (Spanish)
    (93, "JHN.3.16"),      # LSG (French)
    (157, "JHN.3.16"),     # RST (Russian)
    (101, "JHN.3.16"),     # arb: Ketab El Hayat
    (88, "JHN.3.16"),      # Korean RNKSV or similar
    (46, "JHN.3.16"),      # Chinese CUNP
    (1819, "JHN.3.16"),    # Hindi contemporary
    (174, "JHN.3.16"),     # Thai KJV-lineage
    (37, "PSA.23.1"),      # CEB or similar English alt
    (59, "JHN.3.16"),      # ESV
]


async def main() -> None:
    client = BibleClient(load_bible_api_config())
    out = []
    try:
        for version_id, usfm in CANARIES:
            span = await client.verse(version_id, usfm)
            if span is None:
                print(f"SKIP {version_id} {usfm}: absent or merged span")
                continue
            digest = hashlib.sha256(normalize(span.text, "loose").encode()).hexdigest()
            out.append({"version_id": version_id, "usfm": usfm, "sha256_loose": digest})
            print(f"ok   {version_id} {usfm} {digest[:12]}…")
    finally:
        await client.aclose()
    path = Path(__file__).parent.parent / "tests" / "canaries.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {len(out)} canaries -> {path}")


if __name__ == "__main__":
    asyncio.run(main())
