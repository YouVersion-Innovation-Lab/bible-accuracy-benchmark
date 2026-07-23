"""Deterministic scoring for the simple track.

Pure functions: no I/O, no LLM, no randomness. Given a model response, the
ground-truth verse text, distractor-version texts, and same-chapter neighbor
texts, produce a graded, reproducible verdict. ``SCORING_VERSION`` is stamped
into every result record; bumping it re-scores stored responses without
re-querying models.

The headline error metric is QER (Quote Error Rate): character-level
Levenshtein distance divided by the truth length, computed on loose-normalized
text — uniform across spaced and unspaced scripts. Word-level WER is reported
additionally for spaced scripts (human readability only, never scoring).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import regex
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .normalize import normalize

SCORING_VERSION = "1.0.0"

# Severity thresholds (loose-normalized similarity). Tuned during the pilot;
# changes bump SCORING_VERSION.
NEAR_PERFECT_SIM = 0.995
MINOR_SIM = 0.95
MAJOR_SIM = 0.75
WRONG_VERSION_SIM = 0.95
WRONG_VERSION_MARGIN = 0.05
WRONG_VERSE_SIM = 0.90
WRONG_VERSE_TARGET_MAX = 0.50
ATTEMPT_SIM_FLOOR = 0.30      # below this vs every candidate → no_attempt
OVERQUOTE_LEN_RATIO = 1.25

GRADE_FIXED_SCORES = {"perfect": 1.0, "near_perfect": 0.98, "wrong_version": 0.25}

# Unspaced scripts where word-level metrics are meaningless.
_UNSPACED = regex.compile(r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}\p{Khmer}\p{Lao}\p{Myanmar}]")

_BLOCKQUOTE = regex.compile(r"^\s*>\s?", regex.MULTILINE)
_CODE_FENCE = regex.compile(r"^```[a-z]*\s*$", regex.MULTILINE)
_LEADING_VERSE_NUM = regex.compile(r"^\s*\d{1,3}\s*[.:)\]]?\s+")
_TRAILING_PAREN = regex.compile(r"\s*[(\[][^()\[\]]{1,60}[)\]]\s*$")
_LEADING_LABEL_LINE = regex.compile(r"^[^\n]{1,80}[:：]\s*\n")
# Trailing "— John 3:16 NIV" attribution after sentence-final punctuation.
_TRAILING_DASH_ATTR = regex.compile(r"([.!?։。」”\"'])\s*[—–-]\s*[^\n]{1,60}\s*$")
# A short final line that looks like a reference ("John 3:16 NIV").
_TRAILING_REF_LINE = regex.compile(r"\n[^\n]{0,50}\d{1,3}\s*[:.]\s*\d{1,3}[^\n]{0,20}\s*$")
_QUOTED_SPAN = regex.compile(r'"([^"\n]{10,})"')

# Common refusal / inability markers across the benchmark's languages. Used
# only to keep an explicit refusal classified as no_attempt rather than
# fabricated; it never affects the accuracy score (both are 0).
_REFUSAL_MARKERS = (
    "i cannot", "i can't", "i can not", "i'm unable", "i am unable", "i'm not able",
    "i am not able", "i'm sorry", "i am sorry", "i apologize", "cannot provide",
    "can't provide", "unable to provide", "as an ai", "i don't have",
    "no puedo", "lo siento", "je ne peux", "désolé", "ich kann nicht",
    "не могу", "извините", "죄송", "제공할 수 없", "申し訳", "できません",
    "抱歉", "无法", "無法", "ขออภัย", "ไม่สามารถ", "لا أستطيع", "عذرا", "عذراً",
    "नहीं कर सकता", "क्षमा",
)


def _looks_like_refusal(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _REFUSAL_MARKERS)


def _nonspace_len(text: str) -> int:
    return len(regex.sub(r"\s", "", text))


def qer(attempt: str, truth: str) -> float:
    """Quote Error Rate on already-normalized strings. May exceed 1.0."""
    if not truth:
        raise ValueError("truth must be non-empty")
    return Levenshtein.distance(attempt, truth) / len(truth)


def similarity(attempt: str, truth: str) -> float:
    return max(0.0, 1.0 - qer(attempt, truth))


def _best_infix_similarity(needle: str, haystack: str) -> tuple[float, tuple[int, int]]:
    """Best alignment of ``needle`` anywhere inside ``haystack``.

    Returns (similarity of the best window vs needle, (start, end) in
    haystack). rapidfuzz finds the optimal partial alignment; a small
    deterministic edge refinement then maximizes our QER-based similarity.
    """
    if not needle or not haystack:
        return 0.0, (0, 0)
    if len(haystack) <= len(needle):
        return similarity(haystack, needle), (0, len(haystack))
    aln = fuzz.partial_ratio_alignment(needle, haystack)
    if aln is None:
        return 0.0, (0, 0)
    start, end = aln.dest_start, aln.dest_end
    best_sim = similarity(haystack[start:end], needle) if end > start else 0.0
    best_span = (start, end)
    deltas = (-16, -8, -4, -2, -1, 0, 1, 2, 4, 8, 16)
    for ds in deltas:
        for de in deltas:
            s2, e2 = max(0, start + ds), min(len(haystack), end + de)
            if e2 <= s2:
                continue
            s = similarity(haystack[s2:e2], needle)
            if s > best_sim:
                best_sim, best_span = s, (s2, e2)
    return best_sim, best_span


def _candidate_similarity(candidate_loose: str, trivial_loose: str, response_loose: str) -> float:
    """How strongly the response matches a candidate verse text: the better of
    the trivially-stripped attempt and the candidate's own best window in the
    full response (a candidate must get the same extraction chance the target
    verse gets, or wrong-version/wrong-verse detection breaks)."""
    s1 = similarity(trivial_loose, candidate_loose) if trivial_loose else 0.0
    s2, _ = _best_infix_similarity(candidate_loose, response_loose)
    return max(s1, s2)


@dataclass(frozen=True)
class Extraction:
    attempt_loose: str        # loose-normalized extracted quote attempt
    attempt_strict: str       # strict-normalized trivial candidate ("" if window path)
    method: str               # "trivial" | "window"
    format_ok: bool
    trivial_loose: str = ""   # loose form of the trivial candidate (overquote check)


def _trivial_strip(response: str) -> str:
    """Peel obvious wrappers a well-behaved model adds around a bare verse."""
    t = _CODE_FENCE.sub("", response)
    t = _BLOCKQUOTE.sub("", t).strip()
    t = _LEADING_LABEL_LINE.sub("", t, count=1).strip()
    # Enclosing quote pair (after glyph folding happens in normalize; here
    # handle the common raw glyphs directly).
    for opener, closer in [('"', '"'), ("“", "”"), ("«", "»"), ("„", "“"), ("「", "」")]:
        if t.startswith(opener) and t.endswith(closer) and len(t) > 2:
            t = t[len(opener) : -len(closer)].strip()
            break
    t = _LEADING_VERSE_NUM.sub("", t)
    t = _TRAILING_REF_LINE.sub("", t)
    t = _TRAILING_PAREN.sub("", t).strip()
    t = _TRAILING_DASH_ATTR.sub(r"\1", t).strip()
    return t


def extract_attempt(response: str, truth: str) -> Extraction:
    """Isolate the model's quote attempt from its response, deterministically.

    Trivial path: the whole response minus obvious wrappers (models were asked
    for the verse text only). Fallback: best-window alignment of the truth
    inside the response — the model still gets accuracy credit for a quote
    buried in commentary, but loses ``format_ok``.
    """
    truth_loose = normalize(truth, "loose")
    trivial_raw = _trivial_strip(response)
    trivial_loose = normalize(trivial_raw, "loose")
    trivial_sim = similarity(trivial_loose, truth_loose) if trivial_loose else 0.0

    response_loose = normalize(response, "loose")
    window_sim, (ws, we) = _best_infix_similarity(truth_loose, response_loose)

    if trivial_sim >= window_sim - 0.01:
        return Extraction(
            attempt_loose=trivial_loose,
            attempt_strict=normalize(trivial_raw, "strict"),
            method="trivial",
            format_ok=True,
            trivial_loose=trivial_loose,
        )
    return Extraction(
        attempt_loose=response_loose[ws:we],
        attempt_strict="",
        method="window",
        format_ok=False,
        trivial_loose=trivial_loose,
    )


@dataclass(frozen=True)
class ItemScore:
    # grade ∈ perfect | near_perfect | minor | major | wrong_version |
    #         wrong_verse | fabricated | no_attempt
    grade: str
    item_score: float         # 0..1
    qer: float
    wer: float | None         # word-level, spaced scripts only
    verbatim_strict: bool
    verbatim_loose: bool
    format_ok: bool
    overquote: bool
    extraction_method: str
    edit_ops: dict[str, int] = field(default_factory=dict)
    best_distractor: dict | None = None   # {"key": ..., "similarity": ...}
    best_neighbor: dict | None = None     # {"usfm": ..., "similarity": ...}
    scoring_version: str = SCORING_VERSION


def _edit_op_counts(attempt: str, truth: str) -> dict[str, int]:
    counts = {"insert": 0, "delete": 0, "replace": 0}
    for op in Levenshtein.editops(attempt, truth):
        counts[op.tag] += 1
    return counts


def _word_error_rate(attempt: str, truth: str) -> float | None:
    """Word-level edit rate for spaced scripts; None for unspaced scripts."""
    sample = truth[:200]
    if sample and len(_UNSPACED.findall(sample)) / len(sample) > 0.3:
        return None
    truth_words = truth.split()
    if len(truth_words) < 2:
        return None
    return Levenshtein.distance(attempt.split(), truth.split()) / len(truth_words)


def score_item(
    response: str,
    truth: str,
    distractors: dict[str, str] | None = None,
    neighbors: dict[str, str] | None = None,
) -> ItemScore:
    """Score one simple-track response against ground truth.

    ``distractors``: same verse in other versions of the same language
    (key → verse text). ``neighbors``: other verses of the same chapter in the
    target version (usfm → verse text).
    """
    truth_strict = normalize(truth, "strict")
    truth_loose = normalize(truth, "loose")
    ex = extract_attempt(response, truth)
    attempt = ex.attempt_loose

    item_qer = qer(attempt, truth_loose) if attempt else 1.0
    sim_t = max(0.0, 1.0 - item_qer)
    verbatim_strict = bool(ex.attempt_strict) and ex.attempt_strict == truth_strict
    verbatim_loose = attempt == truth_loose

    response_loose = normalize(response, "loose")
    best_d: tuple[str, float] | None = None
    for key, text in (distractors or {}).items():
        s = _candidate_similarity(normalize(text, "loose"), ex.trivial_loose, response_loose)
        if best_d is None or s > best_d[1]:
            best_d = (key, s)

    best_n: tuple[str, float] | None = None
    for usfm_key, text in (neighbors or {}).items():
        s = _candidate_similarity(normalize(text, "loose"), ex.trivial_loose, response_loose)
        if best_n is None or s > best_n[1]:
            best_n = (usfm_key, s)

    overquote = False
    if ex.trivial_loose and len(ex.trivial_loose) >= OVERQUOTE_LEN_RATIO * len(truth_loose):
        infix_sim, _ = _best_infix_similarity(truth_loose, ex.trivial_loose)
        overquote = infix_sim >= MINOR_SIM

    # Did the model produce verse-shaped content at all? Script-agnostic:
    # substantial non-whitespace length, or an explicit quoted span, and not an
    # explicit refusal. This separates "confidently wrong" (fabricated) from
    # "declined / no clear attempt" (no_attempt) even in unspaced scripts where
    # there are no quote marks to key on.
    attempt_chars = _nonspace_len(ex.trivial_loose or "")
    truth_chars = _nonspace_len(truth_loose)
    substantial = attempt_chars >= max(10, 0.4 * truth_chars)
    attempted = (
        not _looks_like_refusal(response)
        and (substantial or bool(_QUOTED_SPAN.search(normalize(response, "strict"))))
    )

    # Severity decision tree (sequential; first match wins).
    d_sim = best_d[1] if best_d else 0.0
    n_sim = best_n[1] if best_n else 0.0
    if verbatim_strict:
        grade = "perfect"
    elif sim_t >= NEAR_PERFECT_SIM:
        grade = "near_perfect"
    elif sim_t >= MINOR_SIM:
        grade = "minor"
    elif sim_t >= MAJOR_SIM:
        grade = "major"
    elif d_sim >= WRONG_VERSION_SIM and d_sim >= sim_t + WRONG_VERSION_MARGIN:
        grade = "wrong_version"
    elif n_sim >= WRONG_VERSE_SIM and sim_t < WRONG_VERSE_TARGET_MAX:
        grade = "wrong_verse"
    elif attempted or max(sim_t, d_sim, n_sim) >= ATTEMPT_SIM_FLOOR:
        grade = "fabricated"
    else:
        grade = "no_attempt"

    if grade in GRADE_FIXED_SCORES:
        score = GRADE_FIXED_SCORES[grade]
    elif grade in ("minor", "major"):
        # Continuous reverse-QER: a credible attempt at the right verse scores in
        # proportion to how close it is (was 1 - 4*QER, which snapped to 0 fast).
        score = sim_t
    else:
        # Miss (wrong verse, fabricated) or non-attempt / refusal scores 0 — a
        # coincidental character overlap is not partial credit.
        score = 0.0

    return ItemScore(
        grade=grade,
        item_score=round(score, 4),
        qer=round(item_qer, 4),
        wer=(
            round(w, 4)
            if attempt and (w := _word_error_rate(attempt, truth_loose)) is not None
            else None
        ),
        verbatim_strict=verbatim_strict,
        verbatim_loose=verbatim_loose,
        format_ok=ex.format_ok,
        overquote=overquote,
        extraction_method=ex.method,
        edit_ops=_edit_op_counts(attempt, truth_loose),
        best_distractor=(
            {"key": best_d[0], "similarity": round(best_d[1], 4)} if best_d else None
        ),
        best_neighbor=(
            {"usfm": best_n[0], "similarity": round(best_n[1], 4)} if best_n else None
        ),
    )
