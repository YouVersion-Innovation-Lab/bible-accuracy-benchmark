"""Process-wide results store with a small TTL cache.

Published results change only when an operator runs `bible-bench publish`, so a
short TTL cache in front of the store keeps almost every request off GCS. The
cache is monotonic-clock based; time is injected so it stays testable.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from dotenv import load_dotenv

from ..results_store import GcsResultsStore, LocalResultsStore, ResultsStore

load_dotenv()


def store_from_env() -> ResultsStore:
    bucket = os.environ.get("BENCH_RESULTS_BUCKET", "").strip()
    if bucket:
        return GcsResultsStore(bucket)
    return LocalResultsStore(os.environ.get("BENCH_LOCAL_DIR", "results").strip() or "results")


class CachedStore:
    def __init__(
        self,
        store: ResultsStore,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._store = store
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, object]] = {}

    def _get(self, key: str, loader: Callable[[], object]) -> object:
        now = self._clock()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        value = loader()
        self._cache[key] = (now, value)
        return value

    def invalidate(self) -> None:
        self._cache.clear()

    def leaderboard(self) -> dict:
        def load() -> dict:
            return self._store.read_json("leaderboard.json") or {"entries": []}
        return self._get("leaderboard", load)  # type: ignore[return-value]

    def published_run_ids(self) -> list[str]:
        def load() -> list[str]:
            out = []
            for run_id in self._store.list_dir("runs"):
                m = self._store.read_json(f"runs/{run_id}/manifest.json")
                if m and m.get("published"):
                    out.append(run_id)
            return out
        return self._get("published_ids", load)  # type: ignore[return-value]

    def is_published(self, run_id: str) -> bool:
        return run_id in self.published_run_ids()

    def summary(self, run_id: str) -> dict | None:
        def load() -> dict | None:
            return self._store.read_json(f"runs/{run_id}/summary.json")
        return self._get(f"summary:{run_id}", load)  # type: ignore[return-value]

    def manifest_meta(self, run_id: str) -> dict | None:
        """Manifest with the heavy item lists stripped (model meta + config only)."""
        _skip = ("items", "topical_items", "phantom_items", "adversarial")

        def load() -> dict | None:
            m = self._store.read_json(f"runs/{run_id}/manifest.json")
            if not m:
                return None
            return {k: v for k, v in m.items() if k not in _skip}
        return self._get(f"manifest:{run_id}", load)  # type: ignore[return-value]

    def items(self, run_id: str, kind: str) -> list[dict]:
        fname = {"simple": "items.jsonl", "topical": "items_topical.jsonl",
                 "phantom": "items_phantom.jsonl",
                 "adversarial": "adversarial.jsonl"}[kind]

        def load() -> list[dict]:
            return self._store.read_jsonl(f"runs/{run_id}/{fname}")
        return self._get(f"items:{run_id}:{kind}", load)  # type: ignore[return-value]

    def responses(self, run_id: str, kind: str) -> list[dict]:
        """The generation records (which carry the prompt) for a track."""
        fname = {"simple": "responses.jsonl", "topical": "responses_topical.jsonl",
                 "phantom": "responses_phantom.jsonl"}.get(kind)
        if not fname:
            return []

        def load() -> list[dict]:
            return self._store.read_jsonl(f"runs/{run_id}/{fname}")
        return self._get(f"responses:{run_id}:{kind}", load)  # type: ignore[return-value]
