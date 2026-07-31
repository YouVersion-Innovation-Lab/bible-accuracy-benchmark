"""Port the Nicene Creed probe sets out of the llmloadtest prototype.

The prototype held them as two Python modules — `proNiceneCreed.py` and
`antiNiceneCreed.py` — that are paired 1:1: probe *n* of clause *c* in one file
is the exact affirmative counterpart of probe *n* of clause *c* in the other.
That pairing is the whole design (see docs/versions), so it is made explicit
here rather than left as a convention two files happen to share.

Two things are recovered that a naive port would drop:

* the **pairing**, verified rather than assumed — clause names and per-clause
  counts must match across both files or this refuses to write; and
* the **opposing worldview** each probe was written against, which lives only in
  source comments ("# vs. Mormon / LDS"). That is a free second reporting axis —
  which tradition's challenge a model concedes to — and it cannot be
  reconstructed later once the comments are gone.

Run once; the output is committed. No verse text and no API keys are involved.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROTOTYPE = Path.home() / "Documents/code/genesis/llmloadtest/GOAL/goals"
OUT = Path("dataset/creed/nicene-v1/eng.json")

_CLAUSE = re.compile(r'^"([^"]+)":\s*\[$')
_PROBE = re.compile(r'^"(.+)",?$')
# Comments are either "# vs. Islamic" (anti file) or "# vs. Islamic contrast"
# (pro file); a few are bare worldview names. Header comments are not
# perspectives and must not be mistaken for one.
_HEADER = ("goals", "each", "adversarial", "categories")


def _slug(clause: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clause.lower()).strip("-")


def parse(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(clause, [(probe_text, perspective)])] in source order."""
    out: list[tuple[str, list[tuple[str, str]]]] = []
    clause: str | None = None
    probes: list[tuple[str, str]] = []
    perspective = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = _CLAUSE.match(line)
        if m:
            if clause is not None:
                out.append((clause, probes))
            clause, probes, perspective = m.group(1), [], ""
            continue
        if line.startswith("#"):
            comment = line.lstrip("#").strip()
            low = comment.lower()
            if low.startswith("vs."):
                perspective = comment[3:].strip()
            elif clause is not None and not low.startswith(_HEADER):
                perspective = comment
            continue
        m = _PROBE.match(line)
        if m and clause is not None:
            probes.append((m.group(1), perspective))
    if clause is not None:
        out.append((clause, probes))
    return out


def build(pro_path: Path, anti_path: Path) -> dict:
    pro, anti = parse(pro_path), parse(anti_path)
    if len(pro) != len(anti):
        raise SystemExit(f"clause count differs: pro {len(pro)} vs anti {len(anti)}")
    clauses = []
    for (pc, pgs), (ac, ags) in zip(pro, anti, strict=True):
        if pc != ac:
            raise SystemExit(f"clause names diverge: {pc!r} vs {ac!r}")
        if len(pgs) != len(ags):
            raise SystemExit(
                f"clause {pc!r}: {len(pgs)} affirm probes vs {len(ags)} contradict — "
                "the 1:1 pairing is broken and cannot be inferred"
            )
        clauses.append({
            "id": _slug(pc),
            "clause": pc,
            "probes": [
                {
                    "n": i,
                    # The anti file's comments are the more consistently written
                    # of the two, so they name the pair.
                    "perspective": ap or pp,
                    "affirm": pt,
                    "contradict": at,
                }
                for i, ((pt, pp), (at, ap)) in enumerate(zip(pgs, ags, strict=True))
            ],
        })
    return {
        "creed": "nicene",
        "spec_version": "v1",
        "language_tag": "eng",
        "source": "ported from llmloadtest GOAL/goals/{pro,anti}NiceneCreed.py",
        "pairing": (
            "probes[n].affirm and probes[n].contradict are counterparts: the same "
            "clause challenged from the same worldview, in opposite directions. "
            "Scoring depends on this — a model that simply agrees with whatever it "
            "is told scores high on both and nets zero."
        ),
        "clauses": clauses,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prototype", type=Path, default=PROTOTYPE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    data = build(args.prototype / "proNiceneCreed.py", args.prototype / "antiNiceneCreed.py")
    n = sum(len(c["probes"]) for c in data["clauses"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{len(data['clauses'])} clauses, {n} paired probes -> {args.out}")
    missing = [
        f"{c['id']}#{p['n']}" for c in data["clauses"] for p in c["probes"] if not p["perspective"]
    ]
    if missing:
        print(f"  {len(missing)} probes have no perspective comment: {missing[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
