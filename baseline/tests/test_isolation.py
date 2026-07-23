"""The baseline must be independent of the benchmark: no import path crosses over."""

from __future__ import annotations

import importlib

import pytest


def test_benchmark_is_not_importable_from_the_baseline():
    # The baseline runs in its own environment with only jittle (jot*) installed.
    # If bible_bench were importable here, the boundary would be leaking.
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bible_bench")


def test_wrapper_modules_import_cleanly():
    for mod in ("bible_baseline.adapter", "bible_baseline.routes", "bible_baseline.llm_client"):
        importlib.import_module(mod)
