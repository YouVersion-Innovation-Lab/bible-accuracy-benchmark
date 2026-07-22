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


def test_failures_version_filter(tmp_path):
    c = _client(tmp_path)
    # Matching version_id keeps the failing item; a non-matching one filters it out.
    assert c.get("/api/runs/run-a/failures?track=simple&version_id=111").json()["total"] == 1
    assert c.get("/api/runs/run-a/failures?track=simple&version_id=999").json()["total"] == 0


def test_cache_control_header(tmp_path):
    # Production TTL → browser caching; dev TTL 0 → no-store.
    assert "max-age=300" in _client(tmp_path, 300).get("/api/leaderboard").headers["cache-control"]
    assert _client(tmp_path, 0).get("/api/leaderboard").headers["cache-control"] == "no-store"


def test_spa_fallback_for_unknown_route(tmp_path):
    # No web build in tests → JSON placeholder, but never a 500.
    assert _client(tmp_path).get("/models/run-a").status_code == 200
