"""A VerseProvider backed by the synthetic '1 Testium' corpus — no scripture.

Implements the async surface QuoteAuditor needs (verse / chapter_verses /
version) so the auditor can be tested fully offline and deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass

# A fake version whose only book, "1 Testium" (TST), maps onto the GEN slot so
# real USFM parsing works. Verse texts are invented.
TESTIUM: dict[str, str] = {
    "GEN.1.1": "In the seventh season the gardener walked through the orchard rows.",
    "GEN.1.2": "And the keeper of the well drew water at dawn each and every morning.",
    "GEN.1.3": "The scribe sealed the ledger with wax and set it in the stone house.",
    "GEN.2.1": "Then the council of elders gathered beneath the wide cedar to speak.",
    "GEN.2.2": "They weighed the grain and divided it fairly among all the families.",
}

LOCAL_BOOK_NAME = "Testamentum"  # a non-English localized name for TST/GEN


@dataclass
class _Span:
    text: str
    extent: int = 1


class FakeProvider:
    def __init__(self, verses: dict[str, str] | None = None):
        self._verses = verses or TESTIUM

    async def verse(self, version_id: int, usfm: str) -> _Span | None:
        text = self._verses.get(usfm)
        return _Span(text) if text else None

    async def chapter_verses(self, version_id: int, chapter_usfm: str) -> dict[str, str]:
        prefix = chapter_usfm.upper() + "."
        return {u: t for u, t in self._verses.items() if u.startswith(prefix)}

    async def version(self, version_id: int) -> dict:
        chapters = sorted({".".join(u.split(".")[:2]) for u in self._verses})
        return {
            "books": [
                {
                    "usfm": "GEN",
                    "human": LOCAL_BOOK_NAME,
                    "human_long": LOCAL_BOOK_NAME,
                    "abbreviation": "Test",
                    "chapters": [
                        {"usfm": c, "canonical": True} for c in chapters
                    ],
                }
            ]
        }
