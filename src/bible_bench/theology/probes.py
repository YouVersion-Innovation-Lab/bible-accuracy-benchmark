"""The question set for Basic Christian Theology: paired Nicene Creed probes.

Every probe exists twice — once affirming a clause of the Creed, once
contradicting it from a named worldview — and both are put to the model. That
pairing is the measurement, not a convenience:

    a model that simply agrees with whatever it is told scores high on BOTH
    directions and nets zero.

Which is why neither direction means much alone. Willingness to affirm, taken by
itself, rewards agreeableness; resistance to contradiction, taken by itself,
rewards stonewalling. Only the pair separates conviction from either.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Direction of a probe. `affirm` puts an orthodox claim to the model and asks
#: whether it will say yes; `contradict` puts the matching heterodox claim and
#: asks whether it can be talked into saying yes.
AFFIRM = "affirm"
CONTRADICT = "contradict"
DIRECTIONS = (AFFIRM, CONTRADICT)

_DATASET = Path(__file__).resolve().parents[3] / "dataset" / "creed" / "nicene-v1"


@dataclass
class TheologyItem:
    """One probe put to one model in one language."""

    id: str
    track: str
    language_tag: str
    direction: str          # affirm | contradict
    clause_id: str
    clause: str             # human-readable creed clause
    perspective: str        # the worldview the challenge comes from
    probe_n: int            # index within the clause; pairs share it
    claim: str              # what the attacker is trying to get the model to affirm

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class CreedSpec:
    """The probe set as loaded from disk, before sampling."""

    creed: str
    spec_version: str
    languages: dict[str, dict] = field(default_factory=dict)

    @property
    def language_tags(self) -> list[str]:
        return sorted(self.languages)


def load_spec(path: Path | str = _DATASET) -> CreedSpec:
    """Load every translation of the probe set.

    The pairing and clause structure must be identical across languages — a
    translation that dropped or merged a probe would silently make one language's
    score incomparable with the rest, so it is rejected here rather than averaged
    in later.
    """
    root = Path(path)
    files = sorted(root.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no creed probe files under {root}")

    languages: dict[str, dict] = {}
    creed = spec_version = ""
    shape: list[tuple[str, int]] | None = None
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        tag = data["language_tag"]
        this_shape = [(c["id"], len(c["probes"])) for c in data["clauses"]]
        if shape is None:
            shape, creed, spec_version = this_shape, data["creed"], data["spec_version"]
        elif this_shape != shape:
            raise ValueError(
                f"{f.name}: clause/probe shape differs from {files[0].name}. Every "
                "language must carry the identical probe set or their scores are "
                "not comparable."
            )
        languages[tag] = data
    return CreedSpec(creed=creed, spec_version=spec_version, languages=languages)


def build_items(
    spec: CreedSpec,
    *,
    seed: str,
    languages: list[str] | None = None,
    per_clause: int | None = None,
) -> list[TheologyItem]:
    """Every probe, in both directions, in every language.

    ``per_clause`` thins to N probes per clause — the fast pass. Thinning is by
    CLAUSE rather than globally so all 21 clauses stay represented: a fast run
    that happened to drop the Trinitarian clauses would not be a small version of
    this benchmark, it would be a different one. The same probes are drawn for
    every language and both directions, so the pairing survives thinning and
    languages stay comparable.
    """
    tags = sorted(languages or spec.language_tags)
    english = spec.languages[next(t for t in ("eng", *tags) if t in spec.languages)]

    # Choose probe indices once, from the seed, and apply that choice everywhere.
    chosen: dict[str, list[int]] = {}
    for clause in english["clauses"]:
        ns = [p["n"] for p in clause["probes"]]
        if per_clause is not None and per_clause < len(ns):
            rng = random.Random(f"{seed}:{clause['id']}")
            ns = sorted(rng.sample(ns, per_clause))
        chosen[clause["id"]] = ns

    items: list[TheologyItem] = []
    for tag in tags:
        for clause in spec.languages[tag]["clauses"]:
            by_n = {p["n"]: p for p in clause["probes"]}
            for n in chosen[clause["id"]]:
                probe = by_n[n]
                for direction in DIRECTIONS:
                    items.append(TheologyItem(
                        id=f"t-{tag}-{clause['id']}-{n}-{direction}",
                        track="theology",
                        language_tag=tag,
                        direction=direction,
                        clause_id=clause["id"],
                        clause=clause["clause"],
                        perspective=probe.get("perspective", ""),
                        probe_n=n,
                        claim=probe[direction],
                    ))
    items.sort(key=lambda i: i.id)
    return items
