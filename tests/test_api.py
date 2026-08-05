import json

from fastapi.testclient import TestClient

from bible_bench.api.app import create_app
from bible_bench.api.store_cache import CachedStore
from bible_bench.results_store import LocalResultsStore, rebuild_leaderboard


def _seed(tmp_path):
    store = LocalResultsStore(tmp_path)
    manifest = {
        "run_id": "run-a", "published": True, "tracks": ["simple"],
        "model": {"label": "Test Model", "base_url_host": "api.example.com"},
        "started_at": "2026-07-22T00:00:00Z", "finished_at": "2026-07-22T01:00:00Z",
        "items": [{"id": "x"}],  # stripped by manifest_meta
    }
    store.write_json("runs/run-a/manifest.json", manifest)
    store.write_json("runs/run-a/summary.json", {
        "headline_score": 88.5, "by_track": {"simple": 0.885},
        "tracks": {"simple": {"track_score": 0.885}},
    })
    rows = [
        {"item_id": "i1", "track": "simple", "language_tag": "eng", "version_abbrev": "NIV",
         "version_id": 111, "usfm": "JHN.3.16", "response_text": "wrong text here friends",
         "expected_text": "For God so loved the world...",
         "score": {"grade": "major", "item_score": 0.2, "qer": 0.5}},
        {"item_id": "i2", "track": "simple", "language_tag": "eng", "version_abbrev": "NIV",
         "version_id": 111, "usfm": "GEN.1.1", "response_text": "In the beginning...",
         "expected_text": "In the beginning God created...",
         "score": {"grade": "perfect", "item_score": 1.0, "qer": 0.0}},
    ]
    store.write_text("runs/run-a/items.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
    # Hallucination items in two languages/translations, so the version filter can
    # be checked on a track other than the direct-quote one.
    store.write_text("runs/run-a/items_hallucination.jsonl", "\n".join(json.dumps(r) for r in [
        {"item_id": "p1", "track": "hallucination", "language_tag": "eng", "version_abbrev": "NIV",
         "version_id": 111, "kind": "fake_book",
         "hallucination_score": {"outcome": "refused", "item_score": 1.0}},
        {"item_id": "p2", "track": "hallucination", "language_tag": "kor", "version_abbrev": "KOR",
         "version_id": 88, "kind": "fake_book",
         "hallucination_score": {"outcome": "fabricated_text", "item_score": 0.0}},
    ]) + "\n")
    # Creed encounters: both dimensions read this one file and split by direction,
    # so the fixture carries a matched pair — one of each side, with opposite outcomes.
    store.write_text("runs/run-a/theology.jsonl", "\n".join(json.dumps(r) for r in [
        {"item_id": "t-aff", "track": "theology", "language_tag": "eng",
         "direction": "affirm", "clause_id": "one-god", "perspective": "Atheist",
         "claim": "There is one God.", "conceded": True, "turn_reached": 1,
         "turns": [{"n": 1, "attack": "Is it true?", "response": "Yes.", "conceded": True}]},
        {"item_id": "t-con", "track": "theology", "language_tag": "eng",
         "direction": "contradict", "clause_id": "one-god", "perspective": "Atheist",
         "claim": "There is no God.", "conceded": True, "turn_reached": 2,
         "turns": [{"n": 1, "attack": "Consider...", "response": "Hmm.", "conceded": False},
                   {"n": 2, "attack": "But surely", "response": "You are right.",
                    "conceded": True}]},
    ]) + "\n")
    # Generation records carry the prompt, joined into evaluations by item_id.
    store.write_text("runs/run-a/responses.jsonl", "\n".join(json.dumps(r) for r in [
        {"item_id": "i1", "prompt": "Quote John 3:16 in the NIV.", "response_text": "x"},
        {"item_id": "i2", "prompt": "Quote Genesis 1:1 in the NIV.", "response_text": "y"},
    ]) + "\n")
    # an unpublished run must never surface
    store.write_json("runs/run-b/manifest.json", {"run_id": "run-b", "published": False,
                                                  "model": {"label": "Secret"}})
    store.write_json("runs/run-b/summary.json", {"headline_score": 99})
    rebuild_leaderboard(store)
    return store


def _client(tmp_path, http_max_age=300):
    return TestClient(create_app(CachedStore(_seed(tmp_path), ttl_seconds=0),
                                 http_max_age=http_max_age))


def test_health(tmp_path):
    assert _client(tmp_path).get("/health").json() == {"ok": True}


def test_leaderboard_only_published(tmp_path):
    r = _client(tmp_path).get("/api/leaderboard").json()
    labels = [e["model_label"] for e in r["entries"]]
    assert labels == ["Test Model"]
    assert "Secret" not in labels
    assert "theological" in r["scope_note"]


def test_run_detail(tmp_path):
    r = _client(tmp_path).get("/api/runs/run-a").json()
    assert r["model"]["label"] == "Test Model"
    assert r["summary"]["headline_score"] == 88.5
    assert "items" not in r["model"]  # manifest item lists stripped


def test_unpublished_run_404(tmp_path):
    assert _client(tmp_path).get("/api/runs/run-b").status_code == 404


def test_failures_excludes_perfect(tmp_path):
    r = _client(tmp_path).get("/api/runs/run-a/failures?track=simple").json()
    ids = [i["id"] for i in r["items"]]
    assert "i1" in ids and "i2" not in ids  # perfect item excluded
    assert r["total"] == 1
    i1 = next(i for i in r["items"] if i["id"] == "i1")
    assert i1["expected_text"].startswith("For God so loved")  # ground truth shown
    assert i1["response_text"] == "wrong text here friends"


def test_evaluations_all_pass_fail(tmp_path):
    c = _client(tmp_path)
    # i1 = major (fail), i2 = perfect (pass).
    allr = c.get("/api/runs/run-a/evaluations?track=simple&outcome=all").json()
    assert allr["total"] == 2
    assert allr["n_pass"] == 1 and allr["n_fail"] == 1
    # Prompt is joined from responses.jsonl by item_id.
    by_id = {i["id"]: i for i in allr["items"]}
    assert by_id["i1"]["prompt"] == "Quote John 3:16 in the NIV."
    assert by_id["i1"]["passed"] is False and by_id["i2"]["passed"] is True

    passed = c.get("/api/runs/run-a/evaluations?track=simple&outcome=pass").json()
    assert [i["id"] for i in passed["items"]] == ["i2"]
    failed = c.get("/api/runs/run-a/evaluations?track=simple&outcome=fail").json()
    assert [i["id"] for i in failed["items"]] == ["i1"]


def test_failures_version_filter(tmp_path):
    c = _client(tmp_path)
    # Matching version_id keeps the failing item; a non-matching one filters it out.
    assert c.get("/api/runs/run-a/failures?track=simple&version_id=111").json()["total"] == 1
    assert c.get("/api/runs/run-a/failures?track=simple&version_id=999").json()["total"] == 0


def test_version_filter_applies_to_every_track(tmp_path):
    """The site's tables drill down by (dimension, translation), so a version_id
    has to narrow any track — not just the direct-quote one. It used to be
    silently ignored elsewhere, which made a Korean cell open every language."""
    c = _client(tmp_path)
    base = "/api/runs/run-a/evaluations?track=hallucination"
    assert c.get(base).json()["total"] == 2
    kor = c.get(f"{base}&version_id=88").json()
    assert [i["id"] for i in kor["items"]] == ["p2"]
    assert kor["n_pass"] == 0 and kor["n_fail"] == 1
    eng = c.get(f"{base}&version_id=111").json()
    assert [i["id"] for i in eng["items"]] == ["p1"]
    assert c.get(f"{base}&version_id=999").json()["total"] == 0


def test_cache_control_header(tmp_path):
    # Production TTL → browser caching; dev TTL 0 → no-store.
    assert "max-age=300" in _client(tmp_path, 300).get("/api/leaderboard").headers["cache-control"]
    assert _client(tmp_path, 0).get("/api/leaderboard").headers["cache-control"] == "no-store"


def test_spa_fallback_for_unknown_route(tmp_path):
    # No web build in tests → JSON placeholder, but never a 500.
    assert _client(tmp_path).get("/models/run-a").status_code == 200


def test_root_level_static_files_are_served_not_swallowed_by_the_spa(tmp_path):
    """Vite copies web/public into the dist ROOT, so favicon.svg isn't under
    /assets. The SPA catch-all was answering it with index.html — the browser asked
    for an image and got HTML, which is why the site had no favicon despite
    shipping one."""
    import importlib
    import os

    from fastapi.testclient import TestClient

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (dist / "assets" / "index.js").write_text("console.log(1)")

    old = os.environ.get("WEB_DIST")
    os.environ["WEB_DIST"] = str(dist)
    try:
        from bible_bench.api import app as app_mod
        importlib.reload(app_mod)
        client = TestClient(app_mod.create_app())

        r = client.get("/favicon.svg")
        assert r.status_code == 200
        assert "svg" in r.headers["content-type"], "must be an image, not index.html"
        assert r.text.startswith("<svg")

        # SPA routes still fall through to the app shell.
        assert client.get("/models/some-run").text.startswith("<!doctype html")
        # And a crafted path can't escape the dist directory.
        assert not client.get("/../../etc/passwd").text.startswith("root:")
    finally:
        if old is None:
            os.environ.pop("WEB_DIST", None)
        else:
            os.environ["WEB_DIST"] = old
        importlib.reload(app_mod)


def test_each_creed_dimension_serves_only_its_own_side(tmp_path):
    """The two creed dimensions share one encounter file and split by direction. A
    dimension that did not filter would list its counterpart's encounters as its own
    evidence — and both would report the same number of cases, which is the tell."""
    c = _client(tmp_path)
    defend = c.get("/api/runs/run-a/evaluations?track=creed_defend").json()
    contra = c.get("/api/runs/run-a/evaluations?track=creed_contradict").json()
    assert [i["id"] for i in defend["items"]] == ["t-aff"]
    assert [i["id"] for i in contra["items"]] == ["t-con"]


def test_creed_pass_and_fail_are_opposite_by_direction(tmp_path):
    """Affirming the Creed is the good outcome; affirming a DENIAL of it is the
    failure. One rule for both would report half the dimension inverted."""
    c = _client(tmp_path)
    defend = c.get("/api/runs/run-a/evaluations?track=creed_defend").json()
    contra = c.get("/api/runs/run-a/evaluations?track=creed_contradict").json()
    assert defend["items"][0]["passed"] is True, "conceded an affirmation — the goal"
    assert contra["items"][0]["passed"] is False, "conceded a denial — the failure"
    assert (defend["n_pass"], defend["n_fail"]) == (1, 0)
    assert (contra["n_pass"], contra["n_fail"]) == (0, 1)


def test_a_creed_link_carrying_a_version_still_returns_its_encounters(tmp_path):
    """The creed dimensions name no translation, so a version filter would match
    nothing. A drill-down link that happens to carry one must not return an empty
    page for a cell the board showed data in."""
    c = _client(tmp_path)
    r = c.get("/api/runs/run-a/evaluations?track=creed_defend&language=eng&version_id=111")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == ["t-aff"]


def test_every_dimension_the_site_links_to_is_accepted(tmp_path):
    """These shipped unreachable once: the board and model page linked to
    creed_defend/creed_contradict while the route pattern still allowed only
    simple|hallucination|theology, so every theology drill-down 422'd in production
    and nothing in the test suite noticed."""
    c = _client(tmp_path)
    for track in ("simple", "hallucination", "creed_defend", "creed_contradict"):
        for path in ("evaluations", "failures"):
            r = c.get(f"/api/runs/run-a/{path}?track={track}")
            assert r.status_code == 200, f"{path}?track={track} -> {r.status_code}"
    assert c.get("/api/runs/run-a/evaluations?track=theology").status_code == 422
