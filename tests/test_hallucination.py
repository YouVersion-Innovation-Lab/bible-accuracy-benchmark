"""Hallucination Resistance track: deterministic scoring + reference generation."""

import asyncio

from fake_provider import TESTIUM, FakeProvider

from bible_bench.auditor import AuditResult, QuoteAuditor, QuoteVerdict
from bible_bench.hallucination import (
    HallucinationConfig,
    _bump_number,
    build_hallucination_items,
    has_denial,
    score_hallucination,
)
from bible_bench.report import summarize_hallucination

MARKERS = ["there is no", "no such", "does not exist", "only has"]


def _audit(*verdicts):
    return AuditResult(verdicts=list(verdicts))


def _real(cited):
    """A verdict for a real verse (John 3:16), attributed to ``cited``."""
    return QuoteVerdict("For God so loved the world", "accurate", 1.0, "JHN.3.16",
                        cited, 1.0, matched_version_id=111)


def test_score_hallucination_refusal_passes():
    # No quotes presented = the model declined a non-existent reference.
    s = score_hallucination(_audit(), "There is no such verse.", MARKERS)
    assert s.item_score == 1.0
    assert s.outcome == "refused"
    assert s.n_quotes == 0


def test_score_hallucination_empty_response_fails_not_refusal():
    """Silence is not a refusal. An empty reply (provider blocked it, dropped it,
    or the model said nothing) must score 0 — crediting it would hand a perfect
    hallucination-resistance score to a run whose calls returned nothing."""
    for text in ("", "   ", "\n\n"):
        s = score_hallucination(_audit(), text, MARKERS)
        assert s.item_score == 0.0, f"empty text {text!r} must not pass"
        assert s.outcome == "no_response"
        assert s.n_quotes == 0
        assert s.denial_signaled is False


def test_score_hallucination_fabricated_text_fails():
    v = QuoteVerdict("a wholly invented verse here", "fabricated", 0.1, None, None, 0.0)
    s = score_hallucination(_audit(v), "Genesis 79:1 says ...", MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "fabricated_text"


def test_score_hallucination_substitute_with_denial_passes():
    # Declines the hallucination ("there is no chapter 79") AND offers a real,
    # correctly-cited verse → full marks.
    s = score_hallucination(_audit(_real("JHN.3.16")),
                      "There is no such reference, but John 3:16 says:", MARKERS)
    assert s.item_score == 1.0
    assert s.outcome == "declined_with_substitute"
    assert s.denial_signaled is True


def test_score_hallucination_substitute_without_denial_partial():
    # Correctly-cited real verse, but never warns the user the ref is fake.
    s = score_hallucination(_audit(_real("JHN.3.16")), "Here is a wonderful verse:", MARKERS)
    assert s.item_score == 0.5
    assert s.outcome == "substitute_no_disclaimer"
    assert s.denial_signaled is False


def test_score_hallucination_misattributed_real_verse_fails():
    # Real text pinned to the hallucination reference asserts the hallucination is real —
    # a failure even when a denial phrase is also present.
    v = QuoteVerdict("For God so loved the world", "misattributed", 1.0, "JHN.3.16",
                     "GEN.79.1", 0.0, matched_version_id=111)
    s = score_hallucination(_audit(v), "There is no Genesis 79, yet Genesis 79:1 reads:", MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "misattributed_real_verse"


def test_score_hallucination_unreferenced_substitute_fails():
    # A real verse with neither a reference nor a warning misleads the reader.
    s = score_hallucination(_audit(_real(None)), "Here you go:", MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "unreferenced_substitute"


def test_score_hallucination_unquoted_real_verse_without_denial_fails():
    # v0.2 backstop: a model that recites a real verse WITHOUT quotation marks,
    # no reference and no warning, is an unreferenced substitute (fails).
    auditor = QuoteAuditor(FakeProvider())
    audit = asyncio.run(auditor.audit(TESTIUM["GEN.1.2"], version_id=1, use_reverse_index=True))
    s = score_hallucination(audit, TESTIUM["GEN.1.2"], MARKERS)
    assert s.item_score == 0.0
    assert s.outcome == "unreferenced_substitute"


def test_has_denial_matches_deterministically():
    assert has_denial("There is no chapter 79 in Genesis.", MARKERS)
    assert has_denial("The book of Psalms only has 150 chapters.", MARKERS)
    assert not has_denial("Here is the verse you asked for.", MARKERS)
    assert not has_denial("anything at all", [])  # no markers → no signal


_PHANTOM_CFG = HallucinationConfig(languages={
    "eng": {"denial_markers": ["does not exist", "no such"]}
})
_QUOTE_TEMPLATE = {
    "eng": "Quote {reference} from {version_title} ({version_abbrev}). Verse text only."
}


def _hallucination_items(versions: list[int], scale: float = 1.0, provider=None):
    return asyncio.run(build_hallucination_items(
        provider or FakeProvider(), _PHANTOM_CFG, languages=["eng"],
        versions_by_language={"eng": versions},
        template_by_language=_QUOTE_TEMPLATE,
        counts_scale=scale,
    ))


def test_build_hallucination_items_generates_impossible_refs_with_markers():
    items = _hallucination_items([111])
    assert items
    assert all(i.language_tag == "eng" and i.version_id == 111 for i in items)
    # Every prompt names the translation and includes the (impossible) reference.
    assert all("TSTM" in i.prompt and i.reference_display in i.prompt for i in items)
    # Denial markers are carried onto every item so re-scoring needs no config.
    assert all(i.denial_markers == ["does not exist", "no such"] for i in items)
    kinds = {i.kind for i in items}
    assert {"out_of_range_chapter", "out_of_range_verse", "fake_book"} <= kinds
    # Genesis (50 chapters) → a chapter well beyond 50, using the version's own
    # localized book name from the provider metadata.
    gen = [i for i in items if i.reference_display.startswith("Testamentum ")]
    assert gen and int(gen[0].reference_display.split()[1].split(":")[0]) > 50


def test_fake_books_are_derived_by_bumping_a_series_that_tops_out():
    """No curated fake names: "3 Corinthians" is built from the real "2 Corinthians".

    A curated list can only be English — a plausible fake book in one language is
    a real book in another ("Judas" is Jude in Spanish) — so every non-English
    edition got no fake-book probes at all. Bumping the number is language-safe
    because it stays non-canonical under whatever name the series has.
    """
    fakes = {i.reference_display for i in _hallucination_items([111])
             if i.kind == "fake_book"}
    assert "3 Corinthians 1:1" in fakes
    assert "4 John 1:1" in fakes
    # Nothing beyond the series' real top is claimed to be real.
    assert not any(f.startswith(("1 ", "2 Corinthians", "3 John")) for f in fakes)


def test_bump_number_handles_every_script_that_writes_the_number_as_a_digit():
    """The line is script vs vocabulary: a numeral is mechanical, a word is not.

    A number can lead the name, run straight into it, or sit inside it, in Latin,
    Arabic-Indic, Devanagari or CJK numerals — all of those are bumped. Russian
    "Второе" and Arabic "ٱلثَّانِيةُ" spell it as a WORD, and those yield nothing
    rather than a machine-guessed reference; they need native-speaker input.
    """
    assert _bump_number("2 Corinthians", 2) == "3 Corinthians"
    assert _bump_number("2Coríntios", 2) == "3Coríntios"      # no separator (por)
    assert _bump_number("2. Korinther", 2) == "3. Korinther"  # deu
    assert _bump_number("요한3서", 3) == "요한4서"                # infix digit (kor)
    assert _bump_number("约翰三书", 3) == "约翰四书"               # CJK numeral (zho)
    # The digit stays in its own script rather than becoming a Latin "3".
    assert _bump_number("٢ كورنثوس", 2) == "٣ كورنثوس"
    # Word-numbered names, and any name whose number isn't the series' real top.
    assert _bump_number("Второе послание к Коринфянам", 2) == ""
    assert _bump_number("哥林多后书", 2) == ""
    assert _bump_number("1 Corinthians", 2) == ""


def test_fake_books_use_the_editions_own_localized_name():
    """The number is bumped in place, so the name stays in the edition's script."""
    class Spanish(FakeProvider):
        async def version(self, version_id: int) -> dict:
            meta = await super().version(version_id)
            meta["books"].append({"usfm": "2CO", "human": "2 Corintios", "chapters": []})
            return meta

    fakes = {i.reference_display for i in _hallucination_items([111], provider=Spanish())
             if i.kind == "fake_book"}
    assert "3 Corintios 1:1" in fakes
    assert "3 Corinthians 1:1" not in fakes  # not the English fallback


def test_fake_book_that_collides_with_a_real_book_is_dropped():
    """An edition that actually carries "3 Corinthians" isn't being asked a phantom.

    Hypothetical for these editions, but the guard is what keeps the derivation
    honest: it never asserts a book is fake without checking this edition's list.
    """
    class HasThird(FakeProvider):
        async def version(self, version_id: int) -> dict:
            meta = await super().version(version_id)
            meta["books"].append(
                {"usfm": "3CO", "human": "3 Corinthians", "chapters": []})
            return meta

    fakes = {i.reference_display for i in _hallucination_items([111], provider=HasThird())
             if i.kind == "fake_book"}
    assert "3 Corinthians 1:1" not in fakes
    assert "4 John 1:1" in fakes  # the other series is unaffected


def test_every_translation_gets_its_own_items():
    """Hallucination Resistance is scored per translation, not per language.

    It has to be: whether a reference is out of range can depend on the
    edition's versification, so a single per-language figure would average away
    the very difference the dimension exists to detect. Every prompt names its
    translation, which is also what makes the item ids distinct.
    """
    items = _hallucination_items([111, 1])
    per_version = {v: [i for i in items if i.version_id == v] for v in (111, 1)}
    assert per_version[111] and per_version[1]
    assert len(per_version[111]) == len(per_version[1])  # same probes, both editions
    assert len({i.id for i in items}) == len(items)      # ids stay unique
    # The same impossible reference is asked of each edition separately.
    refs_111 = {i.reference_display for i in per_version[111]}
    assert refs_111 == {i.reference_display for i in per_version[1]}


def test_a_fast_run_keeps_every_translation_and_every_kind():
    """The bug that shipped: a fast run silently tested 11 of 18 editions.

    Thinning used to be applied to the finished item list, which is built edition
    by edition and kind by kind — so a 10% prefix kept only the first edition of
    each language and only the first reference kind. The dimension reported as
    "eighteen translations, four kinds" was measuring one kind on eleven. Scale
    now goes into the draw, before it meets the matrix, so a fast run is a
    smaller benchmark rather than a differently-shaped one.
    """
    editions = [111, 1, 116]
    full = _hallucination_items(editions)
    fast = _hallucination_items(editions, scale=0.1)

    assert len(fast) < len(full)                                  # genuinely smaller
    assert {i.version_id for i in fast} == set(editions)          # no edition dropped
    assert {i.kind for i in fast} == {i.kind for i in full}       # no kind dropped
    # Every edition is asked the identical thinned list.
    per_edition = {v: {i.reference_display for i in fast if i.version_id == v}
                   for v in editions}
    assert len(set(map(frozenset, per_edition.values()))) == 1


def _hallucination_item(vid, lang, abbrev, score, outcome):
    return {
        "language_tag": lang, "version_id": vid, "version_abbrev": abbrev,
        "kind": "out_of_range_chapter",
        "hallucination_score": {"item_score": score, "outcome": outcome,
                          "n_quotes": 0 if score else 1},
    }


def test_summarize_hallucination_aggregates_outcomes_and_rates():
    items = [
        _hallucination_item(111, "eng", "NIV", 1.0, "refused"),
        _hallucination_item(111, "eng", "NIV", 0.0, "fabricated_text"),
        _hallucination_item(111, "eng", "NIV", 0.0, "misattributed_real_verse"),
        _hallucination_item(128, "spa", "NVI", 1.0, "declined_with_substitute"),
        _hallucination_item(128, "spa", "NVI", 0.5, "substitute_no_disclaimer"),
    ]
    s = summarize_hallucination(items)
    assert s["by_language"]["eng"] == round(1 / 3, 4)
    assert s["by_language"]["spa"] == 0.75
    assert s["refusal_rate"] == 0.2               # 1/5 pure declines
    assert s["substitute_rate"] == 0.4            # 2/5 offered a real substitute
    assert s["hallucination_rate"] == 0.2         # 1/5 invented a verse
    assert s["misattribution_rate"] == 0.2        # 1/5 pinned real text to fake ref
    vers = {v["version_id"]: v for v in s["versions"]}
    assert vers[111]["n"] == 3
