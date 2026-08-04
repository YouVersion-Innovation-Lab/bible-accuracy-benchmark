"""Adding a dimension to a finished run without disturbing the rest of it.

`--only-tracks` exists so a new dimension can be measured on already-published
runs without re-querying every model. That makes it the one code path that writes
to a published run, and it had no coverage at all — which is how both of its bugs
shipped: a crash on the first line it executed, and a silent re-dating of the run.
"""

from bible_bench.cli import _carry_forward, _stamp_completion

PRIOR = {
    "run_key": "v0.5-fast--m",
    "tracks": ["phantom", "simple"],
    "items": [{"id": "s1"}, {"id": "s2"}],
    "phantom_items": [{"id": "p1"}],
    "started_at": "2026-07-30T23:22:16+00:00",
    "finished_at": "2026-07-30T23:28:22+00:00",
    "published": True,
}


def patch(only, fresh=None):
    """A patch invocation's fresh manifest, before the merge."""
    m = {
        "run_key": "v0.5-fast--m",
        "tracks": sorted(only),
        "items": [], "phantom_items": [],
        "started_at": "2026-08-03T19:00:00+00:00",
        "finished_at": None,
        "published": False,
    }
    m.update(fresh or {})
    return _carry_forward(m, PRIOR, set(only))


def test_untouched_dimensions_keep_their_items():
    """A theology patch resamples nothing, so an empty item list must be replaced
    by the stored one — not written through, which would leave the run claiming it
    tested no verses."""
    m = patch({"theology"})
    assert m["items"] == PRIOR["items"]
    assert m["phantom_items"] == PRIOR["phantom_items"]


def test_the_patched_dimension_keeps_its_fresh_items():
    """The converse: re-running a dimension must NOT inherit the old item list."""
    m = patch({"phantom"}, fresh={"phantom_items": [{"id": "p-new"}]})
    assert m["phantom_items"] == [{"id": "p-new"}]
    assert m["items"] == PRIOR["items"], "the others still carry forward"


def test_the_track_list_gains_the_new_dimension_without_losing_the_old():
    m = patch({"theology"})
    assert m["tracks"] == ["phantom", "simple", "theology"]


def test_a_patch_does_not_redate_the_run():
    """The site dates a run by finished_at. Stamping it with the patch time made
    one model claim a different test date from the nine it is ranked against,
    while its scores came from the same July sweep as theirs."""
    m = _stamp_completion(patch({"theology"}), {"theology"}, "2026-08-03T20:00:00+00:00")
    assert m["finished_at"] == PRIOR["finished_at"], "the run's own window is unchanged"
    assert m["patched_at"] == "2026-08-03T20:00:00+00:00", "the patch is still dated"


def test_a_full_run_closes_its_own_window():
    m = _stamp_completion({"finished_at": None}, set(), "2026-08-03T20:00:00+00:00")
    assert m["finished_at"] == "2026-08-03T20:00:00+00:00"
    assert "patched_at" not in m


def test_patching_an_unfinished_run_dates_it_normally():
    """No prior finish means there is no window to preserve — a run interrupted
    before it finished should not be left permanently undated."""
    m = patch({"theology"})
    m["finished_at"] = None
    m = _stamp_completion(m, {"theology"}, "2026-08-03T20:00:00+00:00")
    assert m["finished_at"] == "2026-08-03T20:00:00+00:00"
    assert "patched_at" not in m


def test_published_state_survives_the_patch():
    """Patching must not silently unpublish a live run — the leaderboard reads
    this flag, so flipping it would drop the model off the board."""
    assert patch({"theology"})["published"] is True


def test_patched_tracks_accumulate():
    """Which dimensions were added after the fact is provenance worth keeping."""
    m = _carry_forward(
        {"tracks": ["phantom"], "items": [], "phantom_items": []},
        {**PRIOR, "patched_tracks": ["theology"]},
        {"phantom"},
    )
    assert m["patched_tracks"] == ["phantom", "theology"]
