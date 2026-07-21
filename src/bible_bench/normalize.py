"""Text normalization for quote comparison, script-aware.

Two levels:

- ``strict``: folds presentation-only variation (Unicode form, quote-mark and
  dash glyph variants, whitespace, invisible bidi controls, ALL-CAPS
  small-caps typography like "LORD"/"Lord") while preserving case and
  punctuation otherwise. Used for the "verbatim" verdict.
- ``loose``: strict plus casefold, punctuation removal, and script-specific
  folds (Arabic-script vowel diacritics, zero-width joiners). Used for the
  graded error metric so models aren't penalized for punctuation/casing when
  the words are right.

Both sides of every comparison (model attempt and ground truth) pass through
the same function, so folds only need to be *consistent*, not lossless.
"""

from __future__ import annotations

import unicodedata

import regex

# Quote-ish glyphs → ASCII. Includes CJK corner brackets and guillemets.
_QUOTE_FOLDS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "ʼ": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"', "‹": "'", "›": "'",
    "「": '"', "」": '"', "『": '"', "』": '"',
    "〝": '"', "〞": '"', "＂": '"', "＇": "'",
})

_DASH_FOLDS = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
})

# Invisible directionality/formatting controls that renderers inject freely.
_INVISIBLES = regex.compile(r"[​‎‏‪-‮⁠-⁤⁦-⁩﻿]")

# Zero-width (non-)joiners: orthographically meaningful in Persian, but models
# and keyboards substitute freely between ZWNJ / space / attached — folding to
# nothing on both sides keeps comparisons consistent.
_JOINERS = regex.compile(r"[‌‍]")

# Arabic-script vowel points (harakat), Quranic annotation marks, and tatweel.
# Bible editions differ in pointing; models frequently omit it.
_ARABIC_MARKS = regex.compile(r"[ً-ٰٟۖ-ۭـ]")

# Fully-uppercase alphabetic tokens (len >= 2). Print editions render divine
# names in small caps ("LORD", "SEÑOR"); the chapter HTML extraction loses the
# small-caps styling (the <span class="nd"> wrapper yields "Lord"). Folding
# ALL-CAPS tokens to Capitalized form on both sides makes strict comparison
# typography-insensitive while still catching genuine casing errors ("lord").
_ALLCAPS_TOKEN = regex.compile(r"(?<!\p{L})(\p{Lu}{2,})(?!\p{L})")

# Any Unicode whitespace (incl. NBSP, thin spaces, ideographic space).
_WS = regex.compile(r"\s+")

# All punctuation and symbol marks (for loose mode).
_PUNCT = regex.compile(r"[\p{P}\p{S}]")


def normalize(text: str, level: str = "strict") -> str:
    """Normalize ``text`` at ``level`` ("strict" or "loose")."""
    if level not in ("strict", "loose"):
        raise ValueError(f"Unknown normalization level: {level!r}")
    t = unicodedata.normalize("NFC", text)
    t = _INVISIBLES.sub("", t)
    t = t.translate(_QUOTE_FOLDS).translate(_DASH_FOLDS)
    t = t.replace("…", "...")
    t = _ALLCAPS_TOKEN.sub(lambda m: m.group(1).capitalize(), t)
    if level == "loose":
        t = _JOINERS.sub("", t)
        t = _ARABIC_MARKS.sub("", t)
        t = t.casefold()
        t = _PUNCT.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t
