from fake_provider import LOCAL_BOOK_NAME, TESTIUM, FakeProvider

from bible_bench.auditor import QuoteAuditor, extract_quotes

V1 = TESTIUM["GEN.1.1"]
V2 = TESTIUM["GEN.1.2"]


def test_extract_quotes_min_length():
    assert [q.text for q in extract_quotes('He said "too short" here.')] == []
    assert [q.text for q in extract_quotes('He said "these are four words" here.')] == [
        "these are four words"
    ]


def test_extract_quotes_blockquote():
    spans = extract_quotes("> In the seventh season the gardener walked on.\n\nNext.")
    assert any("gardener walked" in s.text for s in spans)


def test_extract_quotes_cjk_corner_brackets():
    spans = extract_quotes("经文说「第七季园丁走过果园的行列数点」在这里。")
    assert len(spans) == 1


async def test_accurate_cited_quote():
    auditor = QuoteAuditor(FakeProvider())
    text = f'John 1:1 says, "{V1}"'  # GEN slot; "John 1:1" -> JHN not TST
    # Use the localized/English book that maps to GEN: "Genesis 1:1".
    text = f'Genesis 1:1 says, "{V1}"'
    res = await auditor.audit(text, version_id=1, use_reverse_index=False)
    assert len(res.verdicts) == 1
    v = res.verdicts[0]
    assert v.classification == "accurate"
    assert v.matched_usfm == "GEN.1.1"
    assert v.score == 1.0


async def test_localized_reference_resolves():
    auditor = QuoteAuditor(FakeProvider())
    text = f'{LOCAL_BOOK_NAME} 1:1 dice: "{V1}"'
    res = await auditor.audit(text, version_id=1, use_reverse_index=False)
    assert res.verdicts[0].classification == "accurate"
    assert res.verdicts[0].cited_usfm == "GEN.1.1"


async def test_misattributed_quote():
    # Correct verse text, but attributed to the wrong reference.
    auditor = QuoteAuditor(FakeProvider())
    text = f'Genesis 2:1 reads, "{V1}"'
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    v = res.verdicts[0]
    assert v.classification == "misattributed"
    assert v.matched_usfm == "GEN.1.1"
    assert v.cited_usfm == "GEN.2.1"
    assert v.score == 0.0


async def test_mismatch_quote():
    # Cited a real verse, but the quoted words match nothing.
    auditor = QuoteAuditor(FakeProvider())
    text = 'Genesis 1:1 says, "the merchants sailed across the crimson sea at midnight"'
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    v = res.verdicts[0]
    assert v.classification in ("mismatch", "fabricated")
    assert v.score == 0.0


async def test_fabricated_reference():
    auditor = QuoteAuditor(FakeProvider())
    text = f'Genesis 99:1 states, "{V1}"'  # chapter 99 does not exist
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    assert "GEN.99.1" in res.fabricated_refs


async def test_uncited_quote_reverse_index_accurate():
    auditor = QuoteAuditor(FakeProvider())
    text = f'The scripture is clear: "{V2}" This gives us comfort.'
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    v = res.verdicts[0]
    assert v.classification == "accurate"
    assert v.matched_usfm == "GEN.1.2"


async def test_uncited_fabrication_detected_by_reverse_index():
    auditor = QuoteAuditor(FakeProvider())
    text = 'As it says: "Blessed are those who count the stars for they shall never sleep"'
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    v = res.verdicts[0]
    assert v.classification == "fabricated"
    assert v.score == 0.0


async def test_uncited_partial_quote_matches():
    # A substring of a real verse counts as a match.
    auditor = QuoteAuditor(FakeProvider())
    text = 'Remember that "the gardener walked through the orchard rows" today.'
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    assert res.verdicts[0].classification == "accurate"


async def test_no_reverse_index_marks_unverifiable():
    auditor = QuoteAuditor(FakeProvider())
    text = f'Scripture says: "{V2}"'
    res = await auditor.audit(text, version_id=1, use_reverse_index=False)
    assert res.verdicts[0].classification == "unverifiable"
    assert res.verifiable == []


async def test_paraphrase_without_quotes_not_penalized():
    # A loose paraphrase, quoted or not, is not near-verbatim → no verdict at all.
    auditor = QuoteAuditor(FakeProvider())
    text = "The Bible teaches that we should care for the poor and welcome strangers."
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    assert res.verdicts == []


async def test_unquoted_verbatim_verse_detected():
    # v0.2: scripture recited WITHOUT quotation marks is still caught, as long
    # as it's near-verbatim to a real verse.
    auditor = QuoteAuditor(FakeProvider())
    res = await auditor.audit(V2, version_id=1, use_reverse_index=True)
    assert len(res.verdicts) == 1
    v = res.verdicts[0]
    assert v.classification == "accurate"
    assert v.matched_usfm == "GEN.1.2"
    assert v.unquoted is True


async def test_unquoted_paraphrase_below_threshold_not_flagged():
    # A reworded paraphrase of GEN.1.2 sits well under the 90% bar → no verdict,
    # so paraphrase is never converted into a misquote.
    auditor = QuoteAuditor(FakeProvider())
    text = "Each day, whoever looked after the well would go and fetch a bit of water."
    res = await auditor.audit(text, version_id=1, use_reverse_index=True)
    assert res.verdicts == []


async def test_determinism():
    auditor = QuoteAuditor(FakeProvider())
    text = f'Genesis 1:1 says, "{V1}" and Genesis 1:2 says, "{V2}"'
    a = await auditor.audit(text, version_id=1, use_reverse_index=True)
    b = await auditor.audit(text, version_id=1, use_reverse_index=True)
    assert [(v.classification, v.matched_usfm) for v in a.verdicts] == [
        (v.classification, v.matched_usfm) for v in b.verdicts
    ]
