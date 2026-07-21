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
