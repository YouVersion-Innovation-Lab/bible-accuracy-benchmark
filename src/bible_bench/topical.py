"""Topical track: "what does the Bible say about X".

Two elicitation levels: L1 explicitly asks the model to quote the relevant
verses; L2 just asks the direct question. Both expect the model to actually
quote scripture — a paraphrase or a bare reference is not a quotation.

No expected verse — the model chooses what to quote. The deterministic
QuoteAuditor verifies whatever scripture the model presents. Scoring is A × E:

    A = mean accuracy over verifiable quote instances
        (accurate = 1, minor = graded, mismatch/misattributed/fabricated = 0)
    E = 1.0 if the response contains >= 1 verifiable scripture quote, else 0.0

Scoring is strict at both levels: a response that quotes nothing scores 0.
Every item counts in the track mean — this is what stops a model from gaming
the benchmark by quoting a few verses perfectly and declining the rest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .auditor import AuditResult


@dataclass(frozen=True)
class TopicalItem:
    id: str
    track: str
    language_tag: str
    version_id: int
    version_abbrev: str
    topic_id: str
    topic_name: str
    elicitation_level: str    # L1 | L2 | L3
    sensitive: bool
    prompt: str
    accepted_version_ids: list[int] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class TopicalConfig:
    languages: dict[str, dict]
    topics: list[dict]


def load_topics(path: str | Path) -> TopicalConfig:
    data = json.loads(Path(path).read_text())
    return TopicalConfig(languages=data["languages"], topics=data["topics"])


def build_topical_items(
    cfg: TopicalConfig,
    *,
    languages: list[str] | None = None,
    topic_ids: list[str] | None = None,
) -> list[TopicalItem]:
    """Cross topics × languages × elicitation levels into concrete items.

    Each language block declares which levels it runs (English runs L1/L2/L3;
    other languages typically L1/L2), so the matrix stays bounded."""
    langs = languages or list(cfg.languages)
    topics = [t for t in cfg.topics if not topic_ids or t["id"] in topic_ids]
    items: list[TopicalItem] = []
    for lang in langs:
        block = cfg.languages.get(lang)
        if not block:
            continue
        accepted = block.get("accepted_version_ids") or [block["version_id"]]
        for topic in topics:
            name = topic["names"].get(lang)
            if not name:
                continue
            abbrev = block.get("version_abbrev", "")
            for level, template in block["levels"].items():
                prompt = template.replace("{topic}", name).replace("{version}", abbrev)
                items.append(
                    TopicalItem(
                        id=f"t-{lang}-{topic['id']}-{level}",
                        track="topical",
                        language_tag=lang,
                        version_id=block["version_id"],
                        version_abbrev=abbrev,
                        topic_id=topic["id"],
                        topic_name=name,
                        elicitation_level=level,
                        sensitive=bool(topic.get("sensitive")),
                        prompt=prompt,
                        accepted_version_ids=list(accepted),
                    )
                )
    return items


@dataclass
class TopicalScore:
    item_score: float
    accuracy: float | None       # A — None when no verifiable quotes
    emission: float              # E
    n_quotes: int
    n_accurate: int
    n_fabricated: int
    n_fabricated_refs: int
    grades: dict[str, int] = field(default_factory=dict)


def score_topical(audit: AuditResult) -> TopicalScore:
    verifiable = audit.verifiable
    grades: dict[str, int] = {}
    for v in verifiable:
        grades[v.classification] = grades.get(v.classification, 0) + 1
    n_fab = sum(1 for v in verifiable if v.classification == "fabricated")

    # Strict at both levels: a response that quotes nothing scores 0.
    if verifiable:
        accuracy = sum(v.score for v in verifiable) / len(verifiable)
        emission = 1.0
    else:
        accuracy = None
        emission = 0.0

    item_score = (accuracy if accuracy is not None else 0.0) * emission
    return TopicalScore(
        item_score=round(item_score, 4),
        accuracy=round(accuracy, 4) if accuracy is not None else None,
        emission=emission,
        n_quotes=len(verifiable),
        n_accurate=sum(1 for v in verifiable if v.classification == "accurate"),
        n_fabricated=n_fab,
        n_fabricated_refs=len(audit.fabricated_refs),
        grades=grades,
    )
