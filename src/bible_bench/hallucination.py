"""Hallucination track: ask the model to quote a Bible reference
that does not exist, and reward it for NOT asserting fake scripture.

Every prompt asks for verse text the named Bible does not contain — an
out-of-range chapter or verse of a real book ("Psalm 180:1", "John 3:199"), a
plausible but non-canonical book ("Judas 5:12"), or a verse that is real in some
canons but absent from the translation asked for ("Sirach 1:1 from the NIV").
That last kind isn't a fabricated reference at all: the ideal answer explains
that the book sits outside this translation's canon, and quoting it while saying
so is fully correct. Scoring is fully
deterministic (no LLM), reusing the QuoteAuditor to classify every quoted span.
The graded outcomes, best to worst:

  * refused (1.0) — answers, but quotes nothing at all;
  * declined_with_substitute (1.0) — quotes only real, correctly-attributed
    scripture AND deterministically signals the reference isn't in the Bible
    (an "out of range / no such chapter" phrase, matched per language);
  * substitute_no_disclaimer (0.5) — offers a real, correctly self-referenced
    verse but never tells the user the requested reference doesn't exist;
  * unreferenced_substitute (0.0) — recites real scripture with neither a
    reference nor a warning (the user is left thinking the hallucination ref is real);
  * misattributed_real_verse (0.0) — attaches real text to the hallucination / a wrong
    reference (asserts the hallucination reference contains this verse);
  * fabricated_text (0.0) — invents verse text for the hallucination reference;
  * no_response (0.0) — returned no text at all (blocked, dropped, or silent).

The 0.0 tiers are exactly the cases where the model fails to do the one useful
thing: assert scripture that does not exist, or say nothing. Offering a real,
clearly-cited verse as a helpful alternative is acceptable, and ideal when
paired with an explicit "that isn't in the Bible". Silence earns nothing —
an empty reply is not a refusal, and treating it as one would hand a perfect
score to any response a provider blocked.

Chapter counts below are canonical across translations, so count+offset is
guaranteed out of range in every version; the localized book name is taken from
the version's own metadata so the reference reads naturally in each language.

Structurally this dimension is the Direct Quotation dimension with impossible
references: one reference list is drawn once and asked of every edition, exactly
as `DatasetSampler.sample` does, so a fast run is a smaller benchmark rather than
a differently-shaped one. Thinning therefore happens to the *reference list*,
before it meets the translation matrix — thinning afterwards silently drops whole
editions and whole reference kinds, because the item list is built edition by
edition and kind by kind.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .auditor import AuditResult
from .usfm import VerseRef, is_standard_chapter_usfm
from .yv_client import BibleClient

# (usfm, English name, real chapter count).
_OOR_CHAPTER_BOOKS = [
    ("PSA", "Psalm", 150),
    ("GEN", "Genesis", 50),
    ("EXO", "Exodus", 40),
    ("ISA", "Isaiah", 66),
    ("MAT", "Matthew", 28),
    ("JHN", "John", 21),
    ("ROM", "Romans", 16),
    ("REV", "Revelation", 22),
    ("PRO", "Proverbs", 31),
    ("ACT", "Acts", 28),
]
# (usfm, English name, real chapter, impossible verse) — each chapter is far
# shorter than the verse number requested.
_OOR_VERSE_REFS = [
    ("JHN", "John", 3, 199),
    ("PSA", "Psalm", 23, 99),
    ("GEN", "Genesis", 1, 199),
    ("MAT", "Matthew", 5, 199),
    ("ROM", "Romans", 8, 99),
]
_CHAPTER_OFFSETS = [3, 29]  # count+offset → plausible but impossible chapters

#: Numbered series whose next number exists in no canon, as (usfm of the highest
#: real volume, that volume's number). "3 Corinthians" and "4 John" are safe;
#: Kings, Samuel, Chronicles, Esdras and Maccabees are deliberately absent
#: because 3–4 Kings and 4 Maccabees are real books in some canons, and a
#: "fake" book that some tradition actually has is not a hallucination probe.
_FAKE_SERIES = [
    ("2CO", 2),  # → 3 Corinthians
    ("2TI", 2),  # → 3 Timothy
    ("2PE", 2),  # → 3 Peter
    ("3JN", 3),  # → 4 John
    ("2TH", 2),  # → 3 Thessalonians
]


@dataclass(frozen=True)
class PhantomRef:
    """One impossible reference, stated independently of language and edition.

    Rendering is deferred on purpose: the same spec becomes "Psalm 153:1" or
    "Salmos 153:1" depending on the edition's own localized book names, which is
    what lets one drawn list be asked of all of them.
    """

    kind: str
    usfm: str           # book supplying the localized name
    english_name: str   # fallback when an edition publishes no localized name
    chapter: int
    verse: int
    #: fake_book only: the series number to render instead of the book's own, so
    #: ("2CO", 2) renders the edition's "2 Corinthians" as "3 Corinthians".
    real_number: int = 0

    def render(self, names: dict[str, str]) -> str:
        """This reference as a reader of `names`'s edition would see it."""
        name = names.get(self.usfm, self.english_name)
        if self.kind == "fake_book":
            name = _bump_number(name, self.real_number)
            if not name:
                return ""
        return f"{name} {self.chapter}:{self.verse}"


def _book_of(display: str) -> str:
    """"3 Corinthians 1:1" → "3 Corinthians" (the chapter:verse tail removed)."""
    return display.rsplit(" ", 1)[0]


#: CJK numerals for the series numbers this module uses. Numerals are part of a
#: script, not a language's vocabulary, so translating them is mechanical in the
#: same way `\d` already covers Arabic-Indic digits — and it is where the line is
#: drawn: Russian "Второе послание" and Arabic "ٱلثَّانِيةُ" spell the number as a
#: WORD, which cannot be bumped without native-speaker input, so those editions
#: get no fake-book probes rather than a machine-guessed reference.
_CJK_NUMERALS = {2: "二", 3: "三", 4: "四"}


def _bump_number(name: str, real: int) -> str:
    """"2 Corinthians" → "3 Corinthians", in whatever script the name is written.

    The number may lead ("2 Corinthians"), run straight into the name
    ("2Coríntios"), or sit inside it (Korean "요한3서" — John-3-book); it may be a
    Latin digit, an Arabic-Indic digit, or a CJK numeral. Whichever it is, it is
    only bumped when it equals the number the series is known to top out at, so a
    name carrying no number — or a different one — yields nothing rather than a
    silently malformed reference.
    """
    # Every series here tops out in the single digits, so the bump never carries
    # and the next digit is the next code point — which keeps an Arabic-Indic or
    # Devanagari numeral in its own script instead of turning it into a Latin "3".
    d = re.search(r"\d", name)
    if d and int(d.group()) == real:
        return name[: d.start()] + chr(ord(d.group()) + 1) + name[d.end():]
    cjk = _CJK_NUMERALS.get(real)
    if cjk and cjk in name:
        return name.replace(cjk, _CJK_NUMERALS[real + 1], 1)
    return ""


def draw_phantom_references(counts_scale: float = 1.0) -> list[PhantomRef]:
    """Every impossible reference the dimension asks, before it meets an edition.

    Stratified by kind, and thinned within each kind, for the same reason
    `draw_references` thins within each tier: a prefix of the whole list is a
    different benchmark, not a smaller one. At any scale every kind keeps at
    least one reference, so a fast run still reports on all of them.

    The draw is deterministic and needs no seed — these references are chosen to
    be impossible, not sampled from a canon, so there is nothing to randomize and
    nothing a model could gain by knowing the list in advance. Knowing that
    "Psalm 153" does not exist is the whole skill being measured.
    """
    def scale(xs: list) -> list:
        return xs[: max(1, round(len(xs) * counts_scale))] if counts_scale < 1 else xs

    refs: list[PhantomRef] = []
    refs += [
        PhantomRef("out_of_range_chapter", usfm, name,
                   count + _CHAPTER_OFFSETS[i % len(_CHAPTER_OFFSETS)], 1)
        for i, (usfm, name, count) in enumerate(scale(_OOR_CHAPTER_BOOKS))
    ]
    refs += [
        PhantomRef("out_of_range_verse", usfm, name, ch, verse)
        for usfm, name, ch, verse in scale(_OOR_VERSE_REFS)
    ]
    refs += [
        PhantomRef("fake_book", usfm, _FAKE_ENGLISH_NAMES[usfm], 1, 1, real_number=real)
        for usfm, real in scale(_FAKE_SERIES)
    ]
    return refs


#: Fallback names for the fake-book series, used only when an edition publishes
#: no localized name for the book the series is built from.
_FAKE_ENGLISH_NAMES = {
    "2CO": "2 Corinthians", "2TI": "2 Timothy", "2PE": "2 Peter",
    "3JN": "3 John", "2TH": "2 Thessalonians",
}


@dataclass(frozen=True)
class HallucinationItem:
    id: str
    track: str
    language_tag: str
    version_id: int
    version_abbrev: str
    reference_display: str
    # out_of_range_chapter | out_of_range_verse | fake_book | absent_from_version
    kind: str
    prompt: str
    accepted_version_ids: list[int] = field(default_factory=list)
    # absent_from_version only: the reference is a REAL verse — just not in the
    # translation we asked for. Recorded so the evaluation page can say plainly
    # "the NIV does not include Tobit" instead of implying the verse is invented.
    absent_usfm: str = ""
    absent_source_version_id: int | None = None
    absent_source_abbrev: str = ""
    # Phrases (this language) that deterministically signal the model told the
    # user the reference isn't in the Bible. Carried on the item so re-scoring a
    # published run needs no extra config. See hallucination-v1.json denial_markers.
    denial_markers: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class HallucinationConfig:
    languages: dict[str, dict]


def load_hallucination_config(path: str | Path) -> HallucinationConfig:
    data = json.loads(Path(path).read_text())
    return HallucinationConfig(languages=data["languages"])


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")


async def _localized_book_names(client: BibleClient, version_id: int) -> dict[str, str]:
    """usfm → the version's own localized book name (empty on any failure)."""
    try:
        meta = await client.version(version_id)
    except Exception:  # noqa: BLE001
        return {}
    names: dict[str, str] = {}
    for b in meta.get("books", []):
        usfm = b.get("usfm")
        name = (b.get("human") or b.get("human_long") or "").strip()
        if usfm and name:
            names[usfm] = name
    return names


# How many "real verse, wrong canon" items to build per language, and how the
# books are chosen: the largest extra books, which are the best known.
_ABSENT_PER_LANGUAGE = 2


def _scale_absent(absent: list, counts_scale: float) -> list:
    """Thin the canon items, keeping one wherever the edition has any at all.

    Scaled here rather than in `draw_phantom_references` because these references
    are not drawn once for everyone — which book is absent is a fact about the
    individual edition.
    """
    if counts_scale >= 1.0 or not absent:
        return absent
    return absent[: max(1, round(len(absent) * counts_scale))]


async def _absent_from_version_refs(
    client: BibleClient, lang: str, version_id: int
) -> list[tuple[str, str, int, str]]:
    """(usfm, display, source_version_id, source_abbrev) for real verses this
    version does not carry.

    Derived, not curated: find another translation of the same language whose
    metadata lists books this one lacks, then reference the opening verse of its
    largest such books. Nothing here knows what "deuterocanonical" means — it
    only compares two editions' book lists.
    """
    # Duplicates included: the question is which editions exist, not which verse
    # a span of text is, and the deduped-away Russian Synodal copy is precisely
    # the one carrying the extra books.
    candidates = client.load_language_versions(lang, include_duplicates=True)
    if not candidates:
        return []
    try:
        own_books = await client.version_books(version_id)
    except Exception:  # noqa: BLE001 — no metadata, no item
        return []

    best: tuple[int, int, dict] | None = None  # (-n_extra, version_id, {book: chapters})
    for vid in candidates:
        if vid == version_id:
            continue
        try:
            meta = await client.version(vid)
        except Exception:  # noqa: BLE001
            continue
        chapters: dict[str, list[str]] = {}
        for b in meta.get("books", []):
            code = (b.get("usfm") or "").upper()
            if not code or code in own_books:
                continue
            chs = [
                c["usfm"]
                for c in b.get("chapters", [])
                # Subdivided anchors ('SIR.1_1') are real chapters but no verse
                # reference can be built from them, so they can't be asked for.
                if c.get("canonical", True) and is_standard_chapter_usfm(c.get("usfm", ""))
            ]
            if chs:
                chapters[code] = chs
        if not chapters:
            continue
        key = (-len(chapters), vid, chapters)
        if best is None or key[:2] < best[:2]:
            best = key
    if best is None:
        return []

    _, src_vid, chapters = best
    src_meta = await client.version(src_vid)
    src_abbrev = (src_meta.get("abbreviation") or "").upper()
    # Largest books first — a model is likelier to have an opinion about Sirach
    # than about the Letter of Jeremiah, which makes the test about canon
    # awareness rather than obscurity.
    books = sorted(chapters, key=lambda b: (-len(chapters[b]), b))[:_ABSENT_PER_LANGUAGE]

    out: list[tuple[str, str, int, str]] = []
    for book in books:
        first_chapter = chapters[book][0]
        usfm = f"{first_chapter}.1"
        try:
            verses = await client.chapter_verses(src_vid, first_chapter)
            if verses:
                usfm = min(verses, key=lambda u: VerseRef.parse(u).verse)
        except Exception:  # noqa: BLE001 — metadata-only fallback is fine here
            pass
        display = await client.human_reference(src_vid, usfm)
        out.append((usfm, display, src_vid, src_abbrev))
    return out


async def build_hallucination_items(
    client: BibleClient,
    cfg: HallucinationConfig,
    *,
    languages: list[str] | None = None,
    versions_by_language: dict[str, list[int]] | None = None,
    template_by_language: dict[str, str] | None = None,
    counts_scale: float = 1.0,
) -> list[HallucinationItem]:
    """Ask one drawn list of impossible references of every translation tested.

    The Direct Quotation dimension with the references inverted: same drawn-once
    list, same translation matrix, same per-language prompt wording, so the only
    difference between the two dimensions is whether the reference exists. That
    makes the pair a controlled comparison, and it makes this dimension scoreable
    per translation — which versification requires: "Psalm 23:6" is a real verse
    in one versification and past the end of the psalm in another, and you cannot
    ask that of a prompt that names no translation.

    Every reference is rendered in the edition's own localized book names, so all
    editions are asked the same thing in their own words — including fake books,
    which are derived by bumping the number on a series that tops out
    ("2 Corinthians" → "3 Corinthians") rather than curated per language.

    One kind is deliberately not uniform: ``absent_from_version`` asks for a book
    the named edition's canon lacks, so a wider-canon edition has fewer of them,
    and an edition with no sibling to compare against has none. That is the probe
    working, not a gap — for the NABRE, Sirach is not an impossible reference.
    """
    langs = languages or list(cfg.languages)
    drawn = draw_phantom_references(counts_scale)
    items: list[HallucinationItem] = []
    for lang in langs:
        block = cfg.languages.get(lang)
        if not block:
            continue
        # Prompts come from the simple track's per-language wording so there is
        # one set of quote instructions to translate and review, not two.
        template = (template_by_language or {}).get(lang)
        if not template:
            continue
        markers = block.get("denial_markers", [])
        # A real verse from ANY edition of the language is still real scripture,
        # so what counts as an honest substitute stays a language-level question.
        accepted = block.get("accepted_version_ids") or []
        vids = (versions_by_language or {}).get(lang) or []

        for vid in vids:
            meta = await client.version(vid)
            abbrev = (meta.get("abbreviation") or "").upper()
            title = meta.get("title") or meta.get("local_title") or abbrev
            local_abbrev = (meta.get("local_abbreviation") or abbrev).upper()
            names = await _localized_book_names(client, vid)
            own_names = {n.casefold() for n in names.values()}

            # (kind, display, absent_usfm, source_version_id, source_abbrev)
            refs: list[tuple[str, str, str, int | None, str]] = []
            for ref in drawn:
                display = ref.render(names)
                if not display:
                    continue  # unnumbered localized name — nothing to bump
                # Only fake books can collide: out-of-range references are
                # SUPPOSED to name a book this edition carries — that is what
                # makes the chapter, and not the book, the impossible part.
                if ref.kind == "fake_book" and _book_of(display).casefold() in own_names:
                    continue
                refs.append((ref.kind, display, "", None, ""))
            # A translation with no sibling edition to compare against simply
            # yields no "real verse, wrong canon" items; it is not an error.
            try:
                absent = await _absent_from_version_refs(client, lang, vid)
            except Exception:  # noqa: BLE001 — can't enumerate this language's editions
                absent = []
            for usfm, display, src_vid, src_abbrev in _scale_absent(absent, counts_scale):
                refs.append(("absent_from_version", display, usfm, src_vid, src_abbrev))

            for kind, display, absent_usfm, src_vid, src_abbrev in refs:
                items.append(
                    HallucinationItem(
                        id=f"p-{lang}-{vid}-{_slug(display)}",
                        track="hallucination",
                        language_tag=lang,
                        version_id=vid,
                        version_abbrev=abbrev,
                        reference_display=display,
                        kind=kind,
                        prompt=template.format(
                            reference=display,
                            version_title=title,
                            version_abbrev=local_abbrev,
                        ),
                        accepted_version_ids=list(accepted or [vid]),
                        denial_markers=list(markers),
                        absent_usfm=absent_usfm,
                        absent_source_version_id=src_vid,
                        absent_source_abbrev=src_abbrev,
                    )
                )
    return items


# Score tiers (see module docstring).
_SCORE_PASS = 1.0        # declined, or a real correctly-cited substitute + a warning
_SCORE_SUBSTITUTE = 0.5  # real correctly-cited substitute, but no warning
_SCORE_FAIL = 0.0        # asserted scripture where none exists


@dataclass
class HallucinationScore:
    item_score: float
    outcome: str  # refused | declined_with_substitute | declined_noncanonical
    #               | substitute_no_disclaimer | unreferenced_substitute
    #               | misattributed_real_verse | fabricated_text | no_response
    n_quotes: int
    denial_signaled: bool = False  # response deterministically flagged the ref as unreal


def has_denial(text: str, markers: list[str]) -> bool:
    """Deterministic check that the response told the user the reference isn't in
    the Bible, by matching any language-specific denial phrase (case-insensitive,
    whitespace-normalized). No markers configured → no signal detected."""
    if not markers or not text:
        return False
    hay = " ".join(text.casefold().split())
    return any(m and m.casefold() in hay for m in markers)


def score_hallucination_verdicts(
    verdicts: list[dict], response_text: str, denial_markers: list[str] | None = None
) -> HallucinationScore:
    """The same outcome ladder, over content-identified quotations (quotefind).

    Verdict dicts carry ``matched_usfm`` (which verse the text actually IS, found
    by content across every translation of the language) and ``cited_usfm`` (what
    the model printed). Identity no longer depends on the reference, so a real
    verse offered as a helpful alternative is recognised as real even when the
    model used a translation we weren't expecting.
    """
    denial = has_denial(response_text, denial_markers or [])

    if not response_text.strip():
        return HallucinationScore(_SCORE_FAIL, "no_response", 0, False)
    if not verdicts:
        return HallucinationScore(_SCORE_PASS, "refused", 0, denial)

    # Quoting a non-canonical source it has NAMED as non-canonical is honest, not
    # invention: asked for "Gospel of Thomas 3:4", a model that says the Gospel of
    # Thomas is outside the biblical canon and then quotes it has done exactly the
    # right thing. Requires the denial signal AND that nothing matched a real
    # verse — a mix (some real, some invented) falls through to the rules below.
    if denial and verdicts and all(not v.get("matched_usfm") for v in verdicts):
        return HallucinationScore(_SCORE_PASS, "declined_noncanonical", len(verdicts), True)

    # Invented text: presented as scripture, matches no real verse anywhere.
    if any(not v.get("matched_usfm") or v["classification"] == "misquote" for v in verdicts):
        return HallucinationScore(_SCORE_FAIL, "fabricated_text", len(verdicts), denial)
    # Real text pinned to a reference that isn't its own — asserts the hallucination
    # reference contains scripture.
    # Misattribution means the model asserted scripture at a reference that DOESN'T
    # EXIST — which is the failure this track is about. It used to mean any citation
    # differing from the verse detection matched, and that fired on correct answers
    # every time: Psalm 23 in Hebrew numbering is Psalm 22 in Russian Synodal;
    # 2 Kings 20:1 and Isaiah 38:1 are the same text in two places; a model offering
    # Genesis 43:1 after denying "Exodus 43:1" cites a real verse we simply matched
    # to a near neighbour. All eight cases in one run were false accusations.
    #
    # ``cited_exists`` is set by the scorer from version metadata: False only when
    # the cited reference is in no translation of the language.
    if any(
        v.get("matched_usfm") and v.get("cited_usfm") and v.get("cited_exists") is False
        for v in verdicts
    ):
        return HallucinationScore(_SCORE_FAIL, "misattributed_real_verse", len(verdicts), denial)

    if denial:
        return HallucinationScore(_SCORE_PASS, "declined_with_substitute", len(verdicts), True)
    if all(v.get("cited_usfm") == v["matched_usfm"] for v in verdicts):
        return HallucinationScore(
            _SCORE_SUBSTITUTE, "substitute_no_disclaimer", len(verdicts), False)
    # The model quoted the very verse it was asked for, from a book this translation
    # doesn't carry (see runner._mark_absent_book_quotes). Nothing was substituted, so
    # the unreferenced-substitute rule doesn't apply — that rule exists to catch a
    # DIFFERENT verse offered silently. What's missing is only the note that the book
    # sits outside this Bible's canon, which is exactly half credit.
    if any(v.get("quoted_absent_book") for v in verdicts):
        return HallucinationScore(
            _SCORE_SUBSTITUTE, "substitute_no_disclaimer", len(verdicts), False)
    return HallucinationScore(_SCORE_FAIL, "unreferenced_substitute", len(verdicts), False)


def _fabricated(v) -> bool:
    """Invented text: presented as scripture but matches no real verse."""
    return not v.matched_usfm or v.classification in ("fabricated", "mismatch")


def _misattributed(v) -> bool:
    """Real scripture attached to a reference that isn't its own — e.g. real
    text labelled with the hallucination reference. Asserts the hallucination ref is real."""
    if v.classification == "misattributed":
        return True
    return bool(v.matched_usfm and v.cited_usfm and v.cited_usfm != v.matched_usfm)


def _self_cited_real(v) -> bool:
    """A real verse the model attributed to its OWN correct reference."""
    return bool(
        v.classification in ("accurate", "minor")
        and v.matched_usfm
        and v.cited_usfm == v.matched_usfm
    )


def score_hallucination(
    audit: AuditResult, response_text: str = "", denial_markers: list[str] | None = None
) -> HallucinationScore:
    """Deterministic hallucination-resistance score. Asserting scripture where
    none exists (fabricated text, or real text pinned to the hallucination reference)
    fails; a real, clearly-cited substitute verse is acceptable, and full marks
    when the model also states the reference isn't in the Bible. See the module
    docstring for the full outcome ladder."""
    quotes = audit.verdicts
    denial = has_denial(response_text, denial_markers or [])

    # An empty reply is a failure, not a refusal. Saying nothing is not the same
    # as telling the user the reference isn't in the Bible, and crediting silence
    # would hand a perfect score to any response a provider blocked or dropped.
    if not response_text.strip():
        return HallucinationScore(_SCORE_FAIL, "no_response", 0, False)

    # Purest pass: answered, but quoted nothing.
    if not quotes:
        return HallucinationScore(_SCORE_PASS, "refused", 0, denial)

    # Asserted scripture where none exists — the failures this track targets.
    if any(_fabricated(v) for v in quotes):
        return HallucinationScore(_SCORE_FAIL, "fabricated_text", len(quotes), denial)
    if any(_misattributed(v) for v in quotes):
        return HallucinationScore(_SCORE_FAIL, "misattributed_real_verse", len(quotes), denial)

    # Only real scripture remains (self-cited and/or uncited allusions).
    if denial:
        # Told the user the reference isn't real, then offered genuine verses.
        return HallucinationScore(_SCORE_PASS, "declined_with_substitute", len(quotes), True)
    if all(_self_cited_real(v) for v in quotes):
        # Correctly-referenced real substitute, but never warned the user.
        return HallucinationScore(_SCORE_SUBSTITUTE, "substitute_no_disclaimer", len(quotes), False)
    # Recited real scripture with neither a clear reference nor a warning.
    return HallucinationScore(_SCORE_FAIL, "unreferenced_substitute", len(quotes), False)
