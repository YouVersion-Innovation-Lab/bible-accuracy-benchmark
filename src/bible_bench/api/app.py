"""FastAPI app: public read-only results API + the built React SPA.

Endpoints (all read published runs only):

    GET /api/leaderboard                       ranked published runs
    GET /api/runs/{run_id}                      model meta + summary
    GET /api/runs/{run_id}/failures             paginated failing items w/ diffs
    GET /health

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


def create_app(cache: CachedStore | None = None, http_max_age: int | None = None) -> FastAPI:
    app = FastAPI(title="Bible Accuracy Benchmark", docs_url="/api/docs")
    ttl = float(os.environ.get("CACHE_TTL_SECONDS", "300"))
    store = cache or CachedStore(store_from_env(), ttl_seconds=ttl)
    # Browser cache mirrors the server TTL; set CACHE_TTL_SECONDS=0 in dev for
    # always-fresh data. Default 300s in production.
    max_age = int(ttl if http_max_age is None else http_max_age)

    # Note: "/healthz" is intercepted by Google's front end on Cloud Run
    # (returns a GFE 404 before reaching the app), so the health path is
    # "/health".
    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/leaderboard")
    def leaderboard() -> JSONResponse:
        board = store.leaderboard()
        return _cached_json({"scope_note": SCOPE_NOTE, **board}, max_age)

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> JSONResponse:
        if not store.is_published(run_id):
            raise HTTPException(404, "Run not found or not published")
        summary = store.summary(run_id)
        meta = store.manifest_meta(run_id)
        if not summary or not meta:
            raise HTTPException(404, "Run data unavailable")
        return _cached_json({"scope_note": SCOPE_NOTE, "run_id": run_id,
                             "model": meta.get("model", {}), "summary": summary}, max_age)

    @app.get("/api/runs/{run_id}/failures")
    def failures(
        run_id: str,
        track: str = Query("simple", pattern="^(simple|topical|phantom|adversarial)$"),
        language: str | None = None,
        version_id: int | None = None,
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        if not store.is_published(run_id):
            raise HTTPException(404, "Run not found or not published")
        records = store.items(run_id, track)
        failing = _select_failures(records, track, language, version_id)
        page = failing[offset : offset + limit]
        return _cached_json({
            "scope_note": SCOPE_NOTE,
            "run_id": run_id, "track": track, "language": language, "version_id": version_id,
            "total": len(failing), "offset": offset, "limit": limit,
            "items": page,
        }, max_age)

    @app.get("/api/runs/{run_id}/evaluations")
    def evaluations(
        run_id: str,
        track: str = Query("simple", pattern="^(simple|topical|phantom)$"),
        outcome: str = Query("all", pattern="^(all|pass|fail)$"),
        language: str | None = None,
        version_id: int | None = None,
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """Every scored item for a track (not just failures), each with the
        prompt sent and the deterministic scoring detail. Filter by outcome
        (all/pass/fail), language, and — for the direct-quote track — version."""
        if not store.is_published(run_id):
            raise HTTPException(404, "Run not found or not published")
        prompts = {
            r.get("item_id"): r.get("prompt", "") for r in store.responses(run_id, track)
        }
        rows, n_pass, n_fail = _select_evaluations(
            store.items(run_id, track), track, language, version_id, outcome, prompts
        )
        page = rows[offset : offset + limit]
        return _cached_json({
            "scope_note": SCOPE_NOTE,
            "run_id": run_id, "track": track, "outcome": outcome,
            "language": language, "version_id": version_id,
            "total": len(rows), "n_pass": n_pass, "n_fail": n_fail,
            "offset": offset, "limit": limit, "items": page,
        }, max_age)

    _mount_spa(app)
    return app


def _select_failures(
    records: list[dict], track: str, language: str | None, version_id: int | None = None
) -> list[dict]:
    """Failing/interesting records for the browser, newest-severity first."""
    out: list[dict] = []
    for r in records:
        if language and r.get("language_tag") != language:
            continue
        # version_id only applies to the simple track (topical/adversarial items
        # aren't tied to a single version); ignore it elsewhere.
        if version_id is not None and track == "simple" and r.get("version_id") != version_id:
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
        elif track == "phantom":
            ps = r.get("phantom_score", {})
            # A failure is any item where the model quoted something for a
            # reference that does not exist (score < 1 = it did not decline).
            if ps.get("item_score", 1) < 1.0:
                out.append({
                    "id": r["item_id"], "language_tag": r.get("language_tag"),
                    "version_abbrev": r.get("version_abbrev"),
                    "reference": r.get("reference_display"),
                    "kind": r.get("kind"), "outcome": ps.get("outcome"),
                    "score": ps.get("item_score"),
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


def _eval_passed(track: str, r: dict) -> bool:
    """Did this item pass? Per-track definition of a clean result."""
    if track == "simple":
        return r.get("score", {}).get("grade") in ("perfect", "near_perfect")
    if track == "topical":
        ts = r.get("topical_score", {})
        bad = any(
            q.get("classification") in ("mismatch", "misattributed", "fabricated")
            for q in r.get("quotes", [])
        )
        return not bad and ts.get("item_score", 0) >= 1.0
    if track == "phantom":
        return r.get("phantom_score", {}).get("item_score", 0) >= 1.0
    return True


def _eval_row(track: str, r: dict, prompt: str, passed: bool) -> dict:
    """Display record for one evaluation: prompt + response + scoring detail."""
    row = {
        "id": r.get("item_id"),
        "prompt": prompt,
        "response_text": r.get("response_text"),
        "passed": passed,
        "language_tag": r.get("language_tag"),
        "version_abbrev": r.get("version_abbrev"),
    }
    if track == "simple":
        s = r.get("score", {})
        row.update({
            "reference": r.get("usfm"), "usfm": r.get("usfm"),
            "grade": s.get("grade"), "score": s.get("item_score"), "qer": s.get("qer"),
            "expected_text": r.get("expected_text"),
        })
    elif track == "topical":
        ts = r.get("topical_score", {})
        row.update({
            "topic_name": r.get("topic_name"),
            "elicitation_level": r.get("elicitation_level"),
            "sensitive": r.get("sensitive"), "score": ts.get("item_score"),
            "quotes": r.get("quotes", []),
        })
    elif track == "phantom":
        ps = r.get("phantom_score", {})
        row.update({
            "reference": r.get("reference_display"), "kind": r.get("kind"),
            "outcome": ps.get("outcome"), "score": ps.get("item_score"),
            "quotes": r.get("quotes", []),
        })
    return row


def _select_evaluations(
    records: list[dict], track: str, language: str | None,
    version_id: int | None, outcome: str, prompts: dict[str, str],
) -> tuple[list[dict], int, int]:
    """All scored items for the language/version filter, tagged pass/fail, then
    narrowed to the requested outcome. Returns (rows, n_pass, n_fail) where the
    counts are over the full (pre-outcome) filtered set."""
    rows: list[dict] = []
    n_pass = n_fail = 0
    for r in records:
        if language and r.get("language_tag") != language:
            continue
        if version_id is not None and track == "simple" and r.get("version_id") != version_id:
            continue
        passed = _eval_passed(track, r)
        n_pass += int(passed)
        n_fail += int(not passed)
        if (outcome == "pass" and not passed) or (outcome == "fail" and passed):
            continue
        rows.append(_eval_row(track, r, prompts.get(r.get("item_id"), ""), passed))
    # Failures first (lowest score), so problems surface even in the "all" view.
    rows.sort(key=lambda x: (x["passed"], x.get("score") if x.get("score") is not None else 0.0))
    return rows, n_pass, n_fail


def _cached_json(payload: dict, max_age: int) -> JSONResponse:
    if max_age <= 0:
        cc = "no-store"
    else:
        cc = f"public, max-age={max_age}, stale-while-revalidate={max_age * 12}"
    return JSONResponse(payload, headers={"Cache-Control": cc})


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
