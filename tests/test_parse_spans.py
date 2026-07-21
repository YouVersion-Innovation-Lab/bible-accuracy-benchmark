"""parse_spans tests against hand-built HTML replicating the chapter.json
structure (span.verse[data-usfm] / span.content / .note) — filled with fake
text only."""

from bible_bench.yv_client import parse_spans

CHAPTER_HTML = """
<div class="chapter">
  <div class="p">
    <span class="verse" data-usfm="TST.1.1">
      <span class="label">1</span>
      <span class="content">In the seventh season the gardener walked</span>
      <span class="note f">a footnote to be stripped</span>
      <span class="content">through the orchard rows.</span>
    </span>
    <span class="verse" data-usfm="TST.1.2">
      <span class="label">2</span>
      <span class="content">And the keeper of the well drew water at dawn.</span>
    </span>
  </div>
  <div class="p">
    <span class="verse" data-usfm="TST.1.2">
      <span class="content">Measuring each jarful against the mark.</span>
    </span>
    <span class="verse" data-usfm="TST.1.3+TST.1.4">
      <span class="label">3-4</span>
      <span class="content">A merged printed span covering two verses.</span>
    </span>
  </div>
</div>
"""


def test_parse_spans_structure():
    spans = {s.anchor: s for s in parse_spans(CHAPTER_HTML)}
    assert set(spans) == {"TST.1.1", "TST.1.2", "TST.1.3"}


def test_footnotes_stripped():
    spans = {s.anchor: s for s in parse_spans(CHAPTER_HTML)}
    assert "footnote" not in spans["TST.1.1"].text
    assert spans["TST.1.1"].text == (
        "In the seventh season the gardener walked through the orchard rows."
    )


def test_verse_split_across_paragraphs_concatenated():
    spans = {s.anchor: s for s in parse_spans(CHAPTER_HTML)}
    assert spans["TST.1.2"].text == (
        "And the keeper of the well drew water at dawn. "
        "Measuring each jarful against the mark."
    )
    assert spans["TST.1.2"].extent == 1


def test_merged_span_keeps_extent():
    spans = {s.anchor: s for s in parse_spans(CHAPTER_HTML)}
    merged = spans["TST.1.3"]
    assert merged.extent == 2
    assert merged.raw_usfm == "TST.1.3+TST.1.4"


def test_empty_html():
    assert parse_spans("") == []
