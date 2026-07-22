from pathlib import Path

from fake_provider import TESTIUM, FakeProvider

from bible_bench.auditor import QuoteAuditor
from bible_bench.topical import build_topical_items, load_topics, score_topical

V1 = TESTIUM["GEN.1.1"]
V2 = TESTIUM["GEN.1.2"]
TOPICS_PATH = Path(__file__).parent.parent / "dataset" / "topics-v1.json"


def test_topics_file_loads_and_crosses():
    cfg = load_topics(TOPICS_PATH)
    items = build_topical_items(cfg, languages=["eng"])
    # English runs 2 levels (L1, L2) for every topic.
    n_topics = len([t for t in cfg.topics if "eng" in t["names"]])
    assert len(items) == n_topics * 2
    assert any(i.sensitive for i in items)
    assert all(i.prompt and "{topic}" not in i.prompt for i in items)


def test_topics_have_all_declared_languages():
    cfg = load_topics(TOPICS_PATH)
    for lang in cfg.languages:
        items = build_topical_items(cfg, languages=[lang])
        assert items, f"no items built for {lang}"


async def _audit(text):
    return await QuoteAuditor(FakeProvider()).audit(text, version_id=1, use_reverse_index=True)


async def test_accurate_cited_response_scores_full():
    text = f'The Bible speaks to this. Genesis 1:1 says, "{V1}"'
    score = score_topical(await _audit(text))
    assert score.emission == 1.0
    assert score.accuracy == 1.0
    assert score.item_score == 1.0


async def test_fabricated_quote_scores_zero_accuracy():
    text = 'Scripture says: "Blessed are those who count the stars for they never sleep"'
    score = score_topical(await _audit(text))
    assert score.emission == 1.0
    assert score.n_fabricated == 1
    assert score.item_score == 0.0


async def test_refusal_to_quote_scores_zero():
    text = "The Bible has a lot to say about this, but I'd rather not quote specific verses."
    score = score_topical(await _audit(text))
    assert score.n_quotes == 0
    assert score.emission == 0.0
    assert score.item_score == 0.0


async def test_paraphrase_or_bare_reference_scores_zero():
    # Strict: pointing to a verse without quoting it earns nothing at any level.
    text = "This theme runs through Genesis 1:1 and the surrounding passages."
    score = score_topical(await _audit(text))
    assert score.n_quotes == 0
    assert score.emission == 0.0
    assert score.item_score == 0.0


async def test_mixed_accuracy_averages():
    text = (
        f'Genesis 1:1 says, "{V1}" '
        'and it also says in Genesis 1:2: "the merchants sailed the crimson sea at dawn"'
    )
    score = score_topical(await _audit(text))
    assert score.n_quotes == 2
    # One accurate (1.0), one wrong (0.0) → A = 0.5.
    assert score.accuracy == 0.5
    assert score.item_score == 0.5
