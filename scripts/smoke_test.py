#!/usr/bin/env python
"""Fast pre-flight smoke test for the bible-bench pipeline.

Runs a COUPLE of items from each of the three eval dimensions (simple, topical,
phantom) against every model we evaluate, exercising the real generation +
scoring code paths — then sanity-checks that each cell:

  * produced a NON-EMPTY response (no blank / no API error), and
  * is SCORABLE — the scorer ran without throwing and returned a record per item.

It does NOT judge accuracy: a wrong answer that scores 0 still PASSES. The point
is to catch our-own-settings failures (empty output from token starvation,
rejected params, unscorable output, dead endpoints/keys) in ~2 minutes instead
of discovering them hours into a full run.

Run from the repo root:  .venv/bin/python scripts/smoke_test.py
Exit code 0 = all green; 1 = at least one cell failed (usable in CI).
Edit MODELS / N_PER_TRACK below to change coverage.
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from pathlib import Path

# Run everything relative to the repo root (dataset paths, .env, ./bible-cache).
REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

from bible_bench.config import LlmEndpointConfig, load_bible_api_config  # noqa: E402
from bible_bench.dataset import DatasetSampler, load_spec  # noqa: E402
from bible_bench.llm import LlmClient  # noqa: E402
from bible_bench.phantom import build_phantom_items, load_phantom_config  # noqa: E402
from bible_bench.runner import (  # noqa: E402
    generate_phantom,
    generate_simple,
    generate_topical,
    score_phantom_items,
    score_simple,
    score_topical_items,
)
from bible_bench.topical import build_topical_items, load_topics  # noqa: E402
from bible_bench.version import BENCHMARK_VERSION  # noqa: E402
from bible_bench.yv_client import BibleClient  # noqa: E402

N_PER_TRACK = 2  # a "couple" of test cases per dimension

# Every model we've evaluated. base_url / model id / key env var / OpenRouter
# provider pin ("" = none) mirror the real runs. Comment out any you don't want.
ANTHROPIC = "https://api.anthropic.com/v1"
OPENAI = "https://api.openai.com/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER = "https://openrouter.ai/api/v1"
MODELS = [
    dict(label="Claude Sonnet 5",       base=ANTHROPIC,  key="ANTHROPIC_API_KEY",  model="claude-sonnet-5",            provider=""),
    dict(label="Claude Haiku 4.5",      base=ANTHROPIC,  key="ANTHROPIC_API_KEY",  model="claude-haiku-4-5-20251001",  provider=""),
    dict(label="GPT-5.6 Terra",         base=OPENAI,     key="OPENAI_API_KEY",     model="gpt-5.6-terra",              provider=""),
    dict(label="GPT-4o-mini",           base=OPENAI,     key="OPENAI_API_KEY",     model="gpt-4o-mini",                provider=""),
    dict(label="Gemini 3.6 Flash",      base=GEMINI,     key="GEMINI_API_KEY",     model="gemini-3.6-flash",           provider=""),
    dict(label="Gemini 3.5 Flash Lite", base=GEMINI,     key="GEMINI_API_KEY",     model="gemini-3.5-flash-lite",      provider=""),
    dict(label="DeepSeek V4 Pro",       base=OPENROUTER, key="OPENROUTER_API_KEY", model="deepseek/deepseek-v4-pro",   provider=""),
    dict(label="GLM-5.2",               base=OPENROUTER, key="OPENROUTER_API_KEY", model="z-ai/glm-5.2",               provider="z-ai"),
    dict(label="Kimi K3",               base=OPENROUTER, key="OPENROUTER_API_KEY", model="moonshotai/kimi-k3",         provider=""),
    dict(label="Grok 4.5",              base=OPENROUTER, key="OPENROUTER_API_KEY", model="x-ai/grok-4.5",              provider=""),
]

TRACKS = ("simple", "topical", "phantom")


def _cfg(m: dict) -> LlmEndpointConfig:
    routing = {"order": [m["provider"]], "allow_fallbacks": False} if m["provider"] else None
    return LlmEndpointConfig(
        base_url=m["base"], api_key=os.environ.get(m["key"], ""),
        model=m["model"], label=m["label"], provider_routing=routing,
    )


async def build_items(client: BibleClient):
    """A couple of items per track, built the same way a real run builds them."""
    spec = "dataset/spec-v1.json"
    sampler = DatasetSampler(client, load_spec(spec), Path(spec))
    simple = (await sampler.sample(BENCHMARK_VERSION, counts_scale=0.05))[:N_PER_TRACK]
    topical = build_topical_items(load_topics("dataset/topics-v1.json"))[:N_PER_TRACK]
    phantom = (await build_phantom_items(client, load_phantom_config("dataset/phantom-v1.json")))[:N_PER_TRACK]
    return simple, topical, phantom


def _verdict(items, responses, scored) -> tuple[bool, str]:
    """OK iff every item came back non-empty, error-free, and got a scored record."""
    n = len(items)
    real = sum(1 for r in responses if (r.get("response_text") or "").strip())
    errs = [r["error"] for r in responses if r.get("error")]
    n_scored = sum(1 for r in scored if isinstance(r, dict))
    ok = (real == n) and (not errs) and (n_scored == n)
    bits = [f"resp {real}/{n}", f"scored {n_scored}/{n}"]
    if errs:
        bits.append(f"ERR: {errs[0][:60]}")
    elif real < n:
        bits.append("EMPTY output")
    elif n_scored < n:
        bits.append("unscorable / dropped")
    return ok, ", ".join(bits)


async def smoke_model(m: dict, simple, topical, phantom, client: BibleClient) -> dict[str, tuple[bool, str]]:
    model = LlmClient(_cfg(m))
    out: dict[str, tuple[bool, str]] = {}
    # simple
    try:
        resp = await generate_simple(simple, client, model)
        scored = await score_simple({i.id: i for i in simple}, resp, client)
        out["simple"] = _verdict(simple, resp, scored)
    except Exception as e:  # noqa: BLE001
        out["simple"] = (False, f"EXC {type(e).__name__}: {str(e)[:60]}")
    # topical
    try:
        resp = await generate_topical(topical, model)
        scored = await score_topical_items({i.id: i for i in topical}, resp, client)
        out["topical"] = _verdict(topical, resp, scored)
    except Exception as e:  # noqa: BLE001
        out["topical"] = (False, f"EXC {type(e).__name__}: {str(e)[:60]}")
    # phantom
    try:
        resp = await generate_phantom(phantom, model)
        scored = await score_phantom_items({i.id: i for i in phantom}, resp, client)
        out["phantom"] = _verdict(phantom, resp, scored)
    except Exception as e:  # noqa: BLE001
        out["phantom"] = (False, f"EXC {type(e).__name__}: {str(e)[:60]}")
    return out


async def main() -> int:
    client = BibleClient(load_bible_api_config(),
                         cache_dir=os.environ.get("BENCH_CACHE_DIR", "./bible-cache"),
                         offline=True)
    try:
        print(f"Building {N_PER_TRACK} items/track …")
        simple, topical, phantom = await build_items(client)
        print(f"  simple={len(simple)} topical={len(topical)} phantom={len(phantom)}\n")

        results: dict[str, dict] = {}
        details: list[str] = []
        for m in MODELS:
            label = m["label"]
            if not os.environ.get(m["key"], "").strip():
                print(f"{label:24} SKIP (no {m['key']})")
                results[label] = None
                continue
            print(f"{label:24} …", end="", flush=True)
            res = await smoke_model(m, simple, topical, phantom, client)
            results[label] = res
            cells = " ".join(f"{t[:4]}={'ok' if res[t][0] else 'FAIL'}" for t in TRACKS)
            print(f"\r{label:24} {cells}")
            for t in TRACKS:
                if not res[t][0]:
                    details.append(f"  ✗ {label} / {t}: {res[t][1]}")
    finally:
        await client.aclose()

    # Matrix
    print("\n" + "=" * 68)
    print(f"{'MODEL':24} {'SIMPLE':>12} {'TOPICAL':>12} {'PHANTOM':>12}")
    print("-" * 68)
    n_ok = n_tested = 0
    for label, res in results.items():
        if res is None:
            print(f"{label:24} {'— skipped (no key) —':>38}")
            continue
        n_tested += 1
        if all(res[t][0] for t in TRACKS):
            n_ok += 1
        cells = [("✓ " + res[t][1].split(",")[0]) if res[t][0] else "✗ FAIL" for t in TRACKS]
        print(f"{label:24} {cells[0]:>12} {cells[1]:>12} {cells[2]:>12}")
    print("=" * 68)
    if details:
        print("Failures:")
        print("\n".join(details))
    print(f"\nOVERALL: {n_ok}/{n_tested} models fully healthy across all 3 dimensions.")
    return 0 if n_ok == n_tested and n_tested > 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
