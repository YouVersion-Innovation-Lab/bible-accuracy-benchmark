"""Run-artifact storage: a local directory in development, a GCS bucket in
production. Same layout either way:

    runs/{run_id}/manifest.json     run config, seed, item refs, hashes, published flag
    runs/{run_id}/responses.jsonl   raw model output per item (may contain verse text)
    runs/{run_id}/items.jsonl       scored per-item records
    runs/{run_id}/summary.json      aggregate metrics + composite score
    runs/{run_id}/transcripts.jsonl adversarial encounter transcripts
    leaderboard.json                published runs, rebuilt by publish/unpublish

The public site reads only published runs. The results store is the sole
place verse text is persisted; a NIV-style gratis-use / fair-use rationale
covers displaying scattered verses with attribution (confirm with licensing
before public launch).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path


class ResultsStore(ABC):
    @abstractmethod
    def write_text(self, path: str, content: str) -> None: ...

    @abstractmethod
    def read_text(self, path: str) -> str | None: ...

    @abstractmethod
    def list_dir(self, prefix: str) -> list[str]: ...

    @abstractmethod
    def clear(self, prefix: str) -> None:
        """Delete everything under ``prefix`` (used to overwrite a run)."""
        ...

    def write_json(self, path: str, obj: object) -> None:
        self.write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))

    def read_json(self, path: str) -> object | None:
        raw = self.read_text(path)
        return json.loads(raw) if raw is not None else None

    def append_jsonl(self, path: str, rows: Iterable[dict]) -> None:
        existing = self.read_text(path) or ""
        lines = [existing.rstrip("\n")] if existing.strip() else []
        lines.extend(json.dumps(r, ensure_ascii=False) for r in rows)
        self.write_text(path, "\n".join(lines) + "\n")

    def read_jsonl(self, path: str) -> list[dict]:
        raw = self.read_text(path)
        if not raw:
            return []
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


class LocalResultsStore(ResultsStore):
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _p(self, path: str) -> Path:
        return self.root / path

    def write_text(self, path: str, content: str) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read_text(self, path: str) -> str | None:
        p = self._p(path)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def list_dir(self, prefix: str) -> list[str]:
        base = self._p(prefix)
        if not base.exists():
            return []
        return sorted(child.name for child in base.iterdir())

    def clear(self, prefix: str) -> None:
        import shutil

        base = self._p(prefix)
        if base.exists():
            shutil.rmtree(base)


class GcsResultsStore(ResultsStore):
    def __init__(self, bucket: str):
        from google.cloud import storage  # imported lazily; only needed in prod

        self._bucket = storage.Client().bucket(bucket)

    def write_text(self, path: str, content: str) -> None:
        self._bucket.blob(path).upload_from_string(content, content_type="application/json")

    def read_text(self, path: str) -> str | None:
        blob = self._bucket.blob(path)
        return blob.download_as_text() if blob.exists() else None

    def list_dir(self, prefix: str) -> list[str]:
        prefix = prefix.rstrip("/") + "/"
        names = set()
        for blob in self._bucket.list_blobs(prefix=prefix):
            rest = blob.name[len(prefix):]
            if rest:
                names.add(rest.split("/", 1)[0])
        return sorted(names)

    def clear(self, prefix: str) -> None:
        prefix = prefix.rstrip("/") + "/"
        for blob in self._bucket.list_blobs(prefix=prefix):
            blob.delete()


def rebuild_leaderboard(store: ResultsStore) -> dict:
    """Assemble leaderboard.json from all published runs' summaries."""
    entries = []
    for run_id in store.list_dir("runs"):
        manifest = store.read_json(f"runs/{run_id}/manifest.json")
        if not manifest or not manifest.get("published"):
            continue
        summary = store.read_json(f"runs/{run_id}/summary.json")
        if not summary:
            continue
        entries.append(
            {
                "run_id": run_id,
                "run_version": manifest.get("run_version"),
                "model_label": manifest["model"]["label"],
                "provider_host": manifest["model"].get("base_url_host", ""),
                "run_date": manifest.get("finished_at") or manifest.get("started_at"),
                "headline_score": summary.get("headline_score"),
                "by_track": summary.get("by_track", {}),
            }
        )
    entries.sort(key=lambda e: (e["headline_score"] is None, -(e["headline_score"] or 0)))
    leaderboard = {"entries": entries}
    store.write_json("leaderboard.json", leaderboard)
    return leaderboard
