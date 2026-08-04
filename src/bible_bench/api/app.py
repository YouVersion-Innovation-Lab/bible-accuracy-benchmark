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
        track: str = Query("simple", pattern="^(simple|phantom|theology)$"),
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
        track: str = Query("simple", pattern="^(simple|phantom)$"),
        outcome: str = Query("all", pattern="^(all|pass|fail)$"),
        language: str | None = None,
        version_id: int | None = None,
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """Every scored item for a track (not just failures), each with the
        prompt sent and the deterministic scoring detail. Filter by outcome
        (all/pass/fail), language, and Bible version."""
        if not store.is_published(run_id):
            raise HTTPException(404, "Run not found or not published")
        # Join the generation record so each row can show the prompt actually
        # sent plus the call metadata (which upstream served it, why it stopped,
        # token counts) — the raw evidence behind the score.
        sent = {r.get("item_id"): r for r in store.responses(run_id, track)}
        rows, n_pass, n_fail = _select_evaluations(
            store.items(run_id, track), track, language, version_id, outcome, sent
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
        # Every scored item names the translation it was checked against, so a
        # version filter narrows any track. (Theology names no translation — it
        # never quotes scripture — so it drops out entirely when one is asked
        # for, which is the honest answer rather than a silent pass-through.)
        if version_id is not None and r.get("version_id") != version_id:
            continue
        if track == "theology":
            # A failure here is direction-dependent: conceding a DENIAL of the
            # Creed is the failure, whereas conceding an affirmation of it is the
            # desired outcome. One rule for both would report half the dimension
            # backwards.
            conceded = bool(r.get("conceded"))
            failed = conceded if r.get("direction") == "contradict" else not conceded
            if failed or r.get("error"):
                turns = r.get("turns", [])
                out.append({
                    "id": r["item_id"], "language_tag": r.get("language_tag"),
                    "direction": r.get("direction"), "clause_id": r.get("clause_id"),
                    "perspective": r.get("perspective"), "claim": r.get("claim"),
                    "conceded": conceded, "turn_reached": r.get("turn_reached"),
                    "error": r.get("error"),
                    "response_text": turns[-1].get("response") if turns else None,
                    "turns": turns,
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
    if track == "phantom":
        return r.get("phantom_score", {}).get("item_score", 0) >= 1.0
    return True


def _call_meta(sent: dict) -> dict:
    """The model-call metadata worth showing next to a score: which upstream
    served it, why generation stopped, and what it cost."""
    return {
        "finish_reason": sent.get("finish_reason"),
        "refusal": sent.get("refusal"),
        "model_served": sent.get("model_served"),
        "provider": sent.get("provider"),
        "response_id": sent.get("response_id"),
        "input_tokens": sent.get("input_tokens"),
        "output_tokens": sent.get("output_tokens"),
        "reasoning_tokens": sent.get("reasoning_tokens"),
        "error": sent.get("error"),
    }


def _eval_row(track: str, r: dict, sent: dict, passed: bool) -> dict:
    """Display record for one evaluation.

    Carries the FULL deterministic scoring detail, not just the final number, so
    the website can show how each score was derived rather than asserting it.
    """
    row = {
        "id": r.get("item_id"),
        "prompt": sent.get("prompt", ""),
        "response_text": r.get("response_text"),
        "passed": passed,
        "language_tag": r.get("language_tag"),
        "version_abbrev": r.get("version_abbrev"),
        "version_id": r.get("version_id"),
        "call": _call_meta(sent),
    }
    if track == "simple":
        s = r.get("score", {})
        row.update({
            "reference": r.get("usfm"), "usfm": r.get("usfm"),
            "tier": r.get("tier"),
            "canon": r.get("canon"),
            "grade": s.get("grade"), "score": s.get("item_score"), "qer": s.get("qer"),
            "expected_text": r.get("expected_text"),
            # Everything the severity decision tree looked at.
            "wer": s.get("wer"),
            "verbatim_strict": s.get("verbatim_strict"),
            "verbatim_loose": s.get("verbatim_loose"),
            "format_ok": s.get("format_ok"),
            "overquote": s.get("overquote"),
            "extraction_method": s.get("extraction_method"),
            "edit_ops": s.get("edit_ops"),
            "best_distractor": s.get("best_distractor"),
            "best_neighbor": s.get("best_neighbor"),
            "ground_truth_drift": r.get("ground_truth_drift"),
            "scoring_version": s.get("scoring_version"),
        })
    elif track == "phantom":
        ps = r.get("phantom_score", {})
        row.update({
            "reference": r.get("reference_display"), "kind": r.get("kind"),
            # absent_from_version only: a REAL verse, just not in this edition.
            "absent_usfm": r.get("absent_usfm"),
            "absent_source_abbrev": r.get("absent_source_abbrev"),
            "outcome": ps.get("outcome"), "score": ps.get("item_score"),
            "n_quotes": ps.get("n_quotes"),
            "denial_signaled": ps.get("denial_signaled"),
            "quotes": r.get("quotes", []),
            "fabricated_refs": r.get("fabricated_refs", []),
        })
    return row


def _select_evaluations(
    records: list[dict], track: str, language: str | None,
    version_id: int | None, outcome: str, sent: dict[str, dict],
) -> tuple[list[dict], int, int]:
    """All scored items for the language/version filter, tagged pass/fail, then
    narrowed to the requested outcome. Returns (rows, n_pass, n_fail) where the
    counts are over the full (pre-outcome) filtered set."""
    rows: list[dict] = []
    n_pass = n_fail = 0
    for r in records:
        if language and r.get("language_tag") != language:
            continue
        if version_id is not None and r.get("version_id") != version_id:
            continue
        passed = _eval_passed(track, r)
        n_pass += int(passed)
        n_fail += int(not passed)
        if (outcome == "pass" and not passed) or (outcome == "fail" and passed):
            continue
        rows.append(_eval_row(track, r, sent.get(r.get("item_id"), {}), passed))
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
        # Vite copies web/public into the dist ROOT, not into /assets — favicon.svg,
        # icons.svg, and anything added there later. Without this they fall through
        # to the SPA fallback and the browser receives index.html where it asked for
        # an image, which is why the site showed no favicon despite shipping one.
        # Resolved and confined to the dist directory so a crafted path can't escape.
        if full_path:
            candidate = (_WEB_DIST / full_path).resolve()
            try:
                inside = candidate.is_relative_to(_WEB_DIST.resolve())
            except (OSError, ValueError):
                inside = False
            if inside and candidate.is_file():
                return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            {"service": "bible-accuracy-benchmark", "note": SCOPE_NOTE,
             "hint": "Frontend build not present; API is at /api/*"},
        )
