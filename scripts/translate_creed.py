"""Translate the Nicene Creed probe set into every language the benchmark tests.

Two things make this more than a bulk string translation.

**The opposition must survive.** Each probe is a pair: an affirmation of a creed
clause and its exact contradiction, written from the same worldview. The whole
measurement rests on that opposition — a model that agrees with both scores zero,
which is how sycophancy is detected. A translator that softens the contradiction
into something merely "sceptical" silently breaks the instrument. So both halves
of a pair are translated in the same call, with the pairing stated, and the
result is checked for the pair having stayed distinguishable.

**Register matters.** These are creedal claims, and every one of these languages
has an established Christian theological vocabulary ("only-begotten", "of one
substance"). The clause name and the opposing worldview are passed as context so
the translator lands in that register rather than inventing a paraphrase.

Vendor neutrality is not a concern here, unlike for the referee: a probe's text
is only ever read by the *attacker*, never shown to the model under test (it
enters the attacker's system prompt and the attacker writes its own question
from it). So the strongest available translator is the right choice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

SRC = Path("dataset/creed/nicene-v1/eng.json")
OUT_DIR = Path("dataset/creed/nicene-v1")

# The languages the rest of the benchmark tests, by their Bible-API tag.
LANGUAGES = {
    "spa": "Spanish", "por": "Portuguese", "fra": "French", "deu": "German",
    "rus": "Russian", "arb": "Arabic", "hin": "Hindi", "ind": "Indonesian",
    "kor": "Korean", "zho": "Chinese (Simplified)",
}

_SYSTEM = """You are translating theological statements for a research benchmark
that measures whether AI models hold to the Nicene Creed under conversational
pressure.

Each item is a PAIR: an affirmation of a creed clause, and its direct
contradiction written from a specific non-Christian or heterodox perspective.
The pair must remain in exact opposition after translation — if one affirms and
the other merely doubts, the benchmark is broken.

Rules:
1. Use the established Christian theological vocabulary of the target language.
   These are creedal terms with settled translations; do not paraphrase them.
2. Preserve the FULL force of the contradiction. Do not soften, hedge, or add
   disclaimers. You are translating a claim, not endorsing it.
3. Preserve the affirmation's full force likewise.
4. Keep each statement a single self-contained sentence or two, as in the source.
5. Return only JSON. No commentary."""


def _prompt(clause: str, probes: list[dict], language: str) -> str:
    items = [
        {"n": p["n"], "perspective": p["perspective"],
         "affirm": p["affirm"], "contradict": p["contradict"]}
        for p in probes
    ]
    return (
        f'Creed clause: "{clause}"\n'
        f"Target language: {language}\n\n"
        f"Translate every `affirm` and `contradict` below into {language}.\n"
        f"{json.dumps(items, ensure_ascii=False, indent=1)}\n\n"
        'Return JSON: {"probes":[{"n":<int>,"affirm":"...","contradict":"..."}]}'
    )


async def _translate_clause(client, model, clause: dict, lang_name: str, sem) -> list[dict]:
    async with sem:
        last = None
        for attempt in range(4):
            # Retrying a temperature-0 call reproduces the identical bytes, so a
            # malformed response stays malformed however many times you ask. The
            # retry has to change something: first a reminder about escaping (the
            # usual cause is a raw quote inside a CJK string), then jitter.
            temperature = 0.0 if attempt == 0 else 0.2 + 0.2 * attempt
            nudge = "" if attempt == 0 else (
                "\n\nCRITICAL: return STRICTLY valid JSON. Escape every double "
                'quote inside a string value as \\". Use the language\'s own '
                "quotation marks for quoted phrases, never bare ASCII quotes."
            )
            try:
                r = await client.chat.completions.create(
                    model=model, temperature=temperature, max_tokens=6000,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": _SYSTEM + nudge},
                        {"role": "user",
                         "content": _prompt(clause["clause"], clause["probes"], lang_name)},
                    ],
                )
                text = (r.choices[0].message.content or "").strip()
                got = {int(p["n"]): p for p in json.loads(text).get("probes", [])}
                out = []
                for p in clause["probes"]:
                    t = got.get(p["n"])
                    if not t or not t.get("affirm") or not t.get("contradict"):
                        raise ValueError(f"probe {p['n']} missing from response")
                    if t["affirm"].strip() == t["contradict"].strip():
                        raise ValueError(f"probe {p['n']}: pair collapsed to one string")
                    out.append({**p, "affirm": t["affirm"].strip(),
                                "contradict": t["contradict"].strip()})
                return out
            except Exception as e:  # noqa: BLE001 — retry, then surface
                last = e
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"clause {clause['id']!r} -> {lang_name}: {type(last).__name__}: {last}")


async def translate_language(client, model, src: dict, tag: str, sem) -> dict:
    lang_name = LANGUAGES[tag]
    clauses = await asyncio.gather(*(
        _translate_clause(client, model, c, lang_name, sem) for c in src["clauses"]
    ))
    return {
        **{k: v for k, v in src.items() if k != "clauses"},
        "language_tag": tag,
        "language_name": lang_name,
        "translated_from": "eng",
        "translated_by": model,
        "clauses": [{**c, "probes": ps} for c, ps in zip(src["clauses"], clauses, strict=True)],
    }


async def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic/claude-opus-5",
                    help="translator, via OpenRouter. Quality dominates here: a "
                         "mistranslated probe corrupts that language's measurement "
                         "outright, whereas the second-order idiom similarity to one "
                         "vendor is filtered through the attacker's own generation "
                         "before the model under test ever sees it.")
    ap.add_argument("--languages", default="", help="comma-separated tags; default all")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    src = json.loads(SRC.read_text(encoding="utf-8"))
    tags = [t for t in (args.languages.split(",") if args.languages else LANGUAGES) if t.strip()]
    client = AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                         base_url="https://openrouter.ai/api/v1",
                         timeout=300.0, max_retries=2)
    sem = asyncio.Semaphore(args.concurrency)

    for tag in tags:
        dest = OUT_DIR / f"{tag}.json"
        if dest.exists():
            print(f"  {tag}: already present, skipping")
            continue
        data = await translate_language(client, args.model, src, tag, sem)
        dest.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        n = sum(len(c["probes"]) for c in data["clauses"])
        # A translation that came back mostly ASCII for a non-Latin script did
        # not happen; catch it here rather than in a scored run.
        blob = "".join(p["affirm"] for c in data["clauses"] for p in c["probes"])
        ascii_share = sum(ch.isascii() for ch in blob) / max(1, len(blob))
        flag = ""
        if tag in ("arb", "hin", "kor", "zho", "rus") and ascii_share > 0.5:
            flag = f"  !! {ascii_share:.0%} ASCII — likely untranslated"
        print(f"  {tag}: {n} probes -> {dest}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
