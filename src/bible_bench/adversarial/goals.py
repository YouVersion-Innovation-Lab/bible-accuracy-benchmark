"""Adversarial goal loading. A goal is a single (category, target) attack
objective; the committed file stores category strategies + per-target
objectives (references only, never verse text)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Goal:
    id: str
    category: str
    strategy: str
    objective: str
    target_usfm: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class AdversarialConfig:
    language_tag: str
    version_id: int
    accepted_version_ids: list[int]
    turn_depth: int
    goals: list[Goal] = field(default_factory=list)


def load_goals(path: str | Path) -> AdversarialConfig:
    data = json.loads(Path(path).read_text())
    goals: list[Goal] = []
    for cat_name, cat in data["categories"].items():
        strategy = cat["strategy"]
        for i, tgt in enumerate(cat["targets"]):
            slug = (tgt.get("usfm") or f"n{i}").replace(".", "-").lower()
            goals.append(
                Goal(
                    id=f"a-{cat_name}-{slug}",
                    category=cat_name,
                    strategy=strategy,
                    objective=tgt["objective"],
                    target_usfm=tgt.get("usfm"),
                )
            )
    return AdversarialConfig(
        language_tag=data.get("language_tag", "eng"),
        version_id=data["version_id"],
        accepted_version_ids=data.get("accepted_version_ids", [data["version_id"]]),
        turn_depth=data.get("turn_depth", 3),
        goals=goals,
    )
