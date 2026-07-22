"""FastAPI app: public read-only results API + the built React SPA.

Endpoints (all read published runs only):

    GET /api/leaderboard                       ranked published runs
    GET /api/runs/{run_id}                      model meta + summary
    GET /api/runs/{run_id}/failures             paginated failing items w/ diffs
    GET /healthz

Everything else serves the SPA's index.html (client-side routing).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .store_cache import CachedStore, store_from_env

SCOPE_NOTE = (
    "This benchmark scores only the Biblical accuracy of scripture quotations in "
    "model responses. It does not score or rate the theological positions or "
    "theological accuracy of responses."
)

_WEB_DIST = Path(os.environ.get("WEB_DIST", "web/dist"))


def create_app(cache: CachedStore | None = None) -> FastAPI:
    app = FastAPI(title="Bible Accuracy Benchmark", docs_url="/api/docs")
    store = cache or CachedStore(
        store_from_env(), ttl_seconds=float(os.environ.get("CACHE_TTL_SECONDS", "300"))
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/leaderboard")
    def leaderboard() -> JSONResponse:
        board = store.leaderboard()
        return _cached_json({"scope_note": SCOPE_NOTE, **board})

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> JSONResponse:
        if not store.is_published(run_id):
            raise HTTPException(404, "Run not found or not published")
        summary = store.summary(run_id)
        meta = store.manifest_meta(run_id)
        if not summary or not meta:
            raise HTTPException(404, "Run data unavailable")
        return _cached_json({"scope_note": SCOPE_NOTE, "run_id": run_id,
                             "model": meta.get("model", {}), "summary": summary})

    @app.get("/api/runs/{run_id}/failures")
    def failures(
        run_id: str,
        track: str = Query("simple", pattern="^(simple|topical|adversarial)$"),
        language: str | None = None,
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        if not store.is_published(run_id):
            raise HTTPException(404, "Run not found or not published")
        records = store.items(run_id, track)
        failing = _select_failures(records, track, language)
        page = failing[offset : offset + limit]
        return _cached_json({
            "scope_note": SCOPE_NOTE,
            "run_id": run_id, "track": track, "language": language,
            "total": len(failing), "offset": offset, "limit": limit,
            "items": page,
        })

    _mount_spa(app)
    return app


def _select_failures(records: list[dict], track: str, language: str | None) -> list[dict]:
    """Failing/interesting records for the browser, newest-severity first."""
    out: list[dict] = []
    for r in records:
        if language and r.get("language_tag") != language:
            continue
        if track == "adversarial":
            if r.get("reached"):
                bad_turn = next(
                    (t for t in r.get("turns", []) if t.get("confirmed_misquote")), None
                )
                out.append({
                    "id": r["goal_id"], "category": r.get("category"),
                    "target_usfm": r.get("target_usfm"),
                    "attacker": bad_turn.get("attacker") if bad_turn else None,
                    "response_text": bad_turn.get("target") if bad_turn else None,
                    "reasons": bad_turn.get("reasons") if bad_turn else [],
                })
        elif track == "topical":
            ts = r.get("topical_score", {})
            has_bad = any(q.get("classification") in ("mismatch", "misattributed", "fabricated")
                          for q in r.get("quotes", []))
            if has_bad or ts.get("item_score", 1) < 1.0:
                out.append({
                    "id": r["item_id"], "language_tag": r.get("language_tag"),
                    "topic_name": r.get("topic_name"),
                    "elicitation_level": r.get("elicitation_level"),
                    "sensitive": r.get("sensitive"), "score": ts.get("item_score"),
                    "response_text": r.get("response_text"),
                    "quotes": r.get("quotes", []),
                })
        else:  # simple
            s = r.get("score", {})
            if s.get("grade") not in ("perfect", "near_perfect"):
                out.append({
                    "id": r["item_id"], "language_tag": r.get("language_tag"),
                    "version_abbrev": r.get("version_abbrev"), "usfm": r.get("usfm"),
                    "reference": r.get("usfm"), "grade": s.get("grade"),
                    "score": s.get("item_score"), "qer": s.get("qer"),
                    "response_text": r.get("response_text"),
                    "expected_text": r.get("expected_text"),
                })
    # Worst first (lowest score), stable.
    out.sort(key=lambda x: x.get("score", 0.0) if x.get("score") is not None else 0.0)
    return out


def _cached_json(payload: dict) -> JSONResponse:
    return JSONResponse(
        payload,
        headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"},
    )


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA if present; otherwise a minimal placeholder so the
    API is usable in development without a frontend build."""
    assets = _WEB_DIST / "assets"
    index = _WEB_DIST / "index.html"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            {"service": "bible-accuracy-benchmark", "note": SCOPE_NOTE,
             "hint": "Frontend build not present; API is at /api/*"},
        )
