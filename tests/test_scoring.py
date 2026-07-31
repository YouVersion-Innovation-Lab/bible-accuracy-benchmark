from fake_bible import (
    CJK,
    FAKE_CHAPTER,
    LATIN,
    LATIN_ALT_VERSION,
    LATIN_NEIGHBOR,
    THAI,
)

from bible_bench.scoring import extract_attempt, score_item

DISTRACTORS = {"alt-version": LATIN_ALT_VERSION}
NEIGHBORS = {u: t for u, t in FAKE_CHAPTER.items() if t != LATIN}


def test_perfect_verbatim():
    s = score_item(LATIN, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "perfect"
    assert s.item_score == 1.0
    assert s.verbatim_strict and s.verbatim_loose and s.format_ok


def test_perfect_despite_surrounding_quotes():
    s = score_item(f'"{LATIN}"', LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "perfect"


def test_perfect_despite_blockquote_and_reference_line():
    response = f"> {LATIN}\n1 Testium 1:1 (FAKE)"
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "perfect"
    assert s.format_ok


def test_case_change_blocks_perfect_but_scores_high():
    # Strict verbatim fails on casing; loose metric barely moves.
    response = LATIN.replace("the great accounting", "the Great Accounting")
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "near_perfect"
    assert not s.verbatim_strict
    assert s.verbatim_loose
    assert s.item_score >= 0.98


def test_single_character_error_is_near_perfect():
    response = LATIN.replace("sapling", "sapping")
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "near_perfect"


def test_word_swap_is_minor():
    response = LATIN.replace("walked through the orchard", "strolled through the orchard")
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "minor"
    assert 0.5 < s.item_score < 1.0
    assert s.wer is not None and s.wer > 0


def test_wrong_version_detected():
    s = score_item(LATIN_ALT_VERSION, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "wrong_version"
    assert s.item_score == 0.25
    assert s.best_distractor is not None
    assert s.best_distractor["similarity"] >= 0.95


def test_wrong_verse_detected():
    s = score_item(LATIN_NEIGHBOR, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "wrong_verse"
    assert s.item_score == 0.0


def test_fabricated_text():
    response = (
        "And the gardener spoke unto the valley, saying, let every tree be "
        "numbered in the book of seasons, for the harvest waits for the "
        "faithful and the ledger never sleeps."
    )
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "fabricated"
    assert s.item_score == 0.0


def test_refusal_is_no_attempt():
    s = score_item("I'm sorry, I can't provide that text.", LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "no_attempt"
    assert s.item_score == 0.0


def test_wrong_content_in_unspaced_script_is_fabricated_not_refusal():
    # A confidently-wrong CJK "quote" (no ASCII quote marks, low similarity)
    # must be graded fabricated, not no_attempt — it is not a refusal.
    wrong_cjk = "第七季，牧人走过田野，数着天上的星辰，因为夜晚的册子要求忠实的记录。"
    s = score_item(wrong_cjk, CJK, {}, {})
    assert s.grade == "fabricated"
    assert s.item_score == 0.0


def test_refusal_in_other_language_is_no_attempt():
    s = score_item("죄송하지만 그 구절을 제공할 수 없습니다.", CJK, {}, {})
    assert s.grade == "no_attempt"


def test_empty_response_is_no_attempt():
    s = score_item("", LATIN, DISTRACTORS, NEIGHBORS)
    assert s.grade == "no_attempt"


def test_blank_candidate_verses_do_not_crash():
    # A distractor version or chapter neighbor can carry blank text (not every
    # version has every verse). Those must be treated as unmatchable candidates,
    # never fed to qer() as an empty truth (which raises). A correct quote should
    # still score perfect despite the blank candidates alongside it.
    s = score_item(LATIN, LATIN, {"alt-version": "", "other": LATIN_ALT_VERSION},
                   {"NEI.1.2": "", "NEI.1.3": LATIN_NEIGHBOR})
    assert s.grade == "perfect"
    assert s.item_score == 1.0


def test_quote_buried_in_commentary_loses_format_not_accuracy():
    response = (
        "What a wonderful passage this is. The text reads: "
        f'"{LATIN}" '
        "Many readers find the imagery of the ledger deeply comforting, and "
        "scholars have long debated the counting of the saplings."
    )
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert not s.format_ok
    assert s.extraction_method == "window"
    assert s.grade in ("near_perfect", "minor")
    assert s.item_score >= 0.8


def test_overquote_flagged():
    response = f"{LATIN} {LATIN_NEIGHBOR}"
    s = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert s.overquote


def test_unspaced_script_scores_char_level():
    s = score_item(THAI, THAI, {}, {})
    assert s.grade == "perfect"
    assert s.wer is None  # word metrics meaningless for Thai
    wrong = THAI[:-8] + THAI[-4:]  # drop a few characters
    s2 = score_item(wrong, THAI, {}, {})
    assert s2.grade in ("near_perfect", "minor")
    assert s2.qer > 0


def test_cjk_perfect():
    s = score_item(CJK, CJK, {}, {})
    assert s.grade == "perfect"
    assert s.wer is None


def test_deterministic_repeat():
    response = LATIN.replace("counted", "recounted")
    a = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    b = score_item(response, LATIN, DISTRACTORS, NEIGHBORS)
    assert a == b


def test_extract_trivial_path_for_clean_response():
    ex = extract_attempt(LATIN, LATIN)
    assert ex.method == "trivial"
    assert ex.format_ok


def test_minor_error_scores_continuous_reverse_qer():
    # A quote with a small error is graded minor/major and scored as reverse-QER
    # (1 - QER), not the old steep 1 - 4*QER that snapped partial quotes to zero.
    resp = LATIN.replace("gardener", "farmer")  # one-word change
    s = score_item(resp, LATIN, {}, {})
    assert s.grade in ("minor", "major")
    assert abs(s.item_score - (1.0 - s.qer)) < 1e-6
    assert s.item_score > 0.85  # a single-word change is close, not near-zero


def test_verbatim_from_another_translation_is_wrong_version_not_fabricated():
    """The bug this replaced: only four hand-picked distractors were checked, so a
    faithful quotation from any other edition was recorded as invented text. Now
    every translation of the language is a candidate."""
    # Nahum 3:1 as it actually happened: asked in the NABRE, answered verbatim from
    # another edition, similarity to the requested text only 0.38 — so the old tree
    # called it invented scripture.
    truth = "Ah! The bloody city, all lies, Full of plunder, whose looting never stops!"
    other = "Woe to the city of bloodshed, totally deceitful, full of plunder, endless prey!"
    # Keyed by version id, which is what score_simple now supplies for every
    # translation of the language rather than a configured few.
    s = score_item(other, truth, {"3523": other}, {})
    assert s.grade == "wrong_version"
    assert s.item_score == 0.25


def test_recognisable_attempt_is_severe_not_fabricated():
    """0.60-0.75 similarity to the requested verse is a recognisable attempt at it.
    It used to fall to "fabricated" and score 0, so 0.750 earned 0.75 and 0.749
    earned nothing."""
    truth = ("Timna was a concubine of Eliphaz, the son of Esau, and she bore Amalek "
             "to Eliphaz. Those were the sons of Adah, the wife of Esau.")
    attempt = ("Timna was a concubine of Esau's son Eliphaz, and she bore Amalek to "
               "Eliphaz. These were the descendants of Esau's wife Adah.")
    s = score_item(attempt, truth, {}, {})
    assert s.grade == "severe"
    assert 0.6 <= s.item_score < 0.75, "scored on how close it is, not zero"


def test_no_cliff_across_the_severe_boundary():
    """Scores must be continuous through the band edges. The old tree dropped from
    0.75 to 0.00 at MAJOR_SIM, so one edit could cost three quarters of the mark."""
    truth = "a" * 200
    scores = []
    for keep in range(120, 200, 4):          # similarity ~0.60 upward
        attempt = "a" * keep + "z" * (200 - keep)
        s = score_item(attempt, truth, {}, {})
        scores.append(s.item_score)
    steps = list(zip(scores, scores[1:], strict=False))
    assert all(b >= a for a, b in steps), "score must be monotonic"
    assert scores[0] > 0.0, "the bottom of the severe band still earns credit"
    assert all(abs(b - a) < 0.10 for a, b in steps), "no step changes"


def test_a_polite_copyright_decline_is_a_decline_not_an_invention():
    """GPT-5.6 Terra declines in-copyright translations by name (FINDINGS F-1).
    Two compounding defects graded 25 of those as invented scripture:

    * the markers are written with an ASCII apostrophe and the model writes
      U+2019, so the refusal wasn't recognised at all; and
    * the attempt floor then fired on ~30% coincidental character overlap with a
      neighbouring verse, overriding the refusal even once it WAS recognised.

    The score is 0 either way — declining is a scored failure by design — but
    "invented a verse" is a false accusation about a model that invented nothing.
    """
    verse = ("And if the bugler doesn't sound a clear call, how will the soldiers "
             "know they are being called to battle?")
    for text in (
        "Sorry, I can’t provide that verse verbatim from the NLT.",          # curly
        "Sorry, I can't provide that verse verbatim from the NLT.",               # ascii
        "Sorry, I can’t provide that verse from the NLT, but I can summarize "
        "it or provide it in a public-domain translation.",
    ):
        s = score_item(text, verse, {}, {})
        assert s.grade == "no_attempt", f"{text[:40]!r} graded {s.grade}"
        assert s.item_score == 0.0


def test_declining_one_edition_while_quoting_another_is_still_wrong_version():
    """The refusal must not swallow a real quotation. A model that says it can't
    give the requested edition and then quotes a different one HAS quoted
    scripture, and the ordered tree catches that before the refusal branch."""
    requested = "Ah! The bloody city, all lies, Full of plunder, whose looting never stops!"
    other_edition = ("Woe to the city of bloodshed, totally deceitful, full of plunder, "
                     "endless prey!")
    # Declines the edition, then quotes the one asked for anyway.
    s = score_item(
        f"I can't provide the NIV text, but this translation reads: “{requested}”",
        requested, {}, {},
    )
    assert s.grade in ("perfect", "near_perfect", "minor"), s.grade
    # Declines, then quotes a DIFFERENT edition of the same verse — real
    # scripture from the wrong Bible, which is wrong_version and not a decline.
    s2 = score_item(
        f"I can't provide that translation. Another reads: “{other_edition}”",
        requested, {"3523": other_edition}, {},
    )
    assert s2.grade == "wrong_version", s2.grade
