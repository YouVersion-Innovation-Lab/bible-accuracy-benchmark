"""The benchmark version lives here, in the codebase — it is NOT passed on the
command line. Each version is an independently-scored generation of the
benchmark (its tracks, prompts, and scoring rules); bumping it should come with
a matching ``docs/versions/<version>.md`` description and a "Changes from …"
delta. Runs recorded at an older version stay frozen at that version.

The version also seeds the per-run verse sample, so every model evaluated at a
given version is tested on the identical set (a fresh draw per version)."""

from __future__ import annotations

BENCHMARK_VERSION = "v0.2"
