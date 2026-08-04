/**
 * The site has two boards: the benchmark proper, and the Extended Benchmark
 * (beta) that carries dimensions we're still settling.
 *
 * They are rendered by the SAME components, because a reader who has learned to
 * read one should not have to learn a second convention to read the other. This
 * file is the only place they differ — everything a board or report needs to
 * know about "which benchmark am I" lives in one object, so adding or promoting
 * a dimension is an edit here rather than a second copy of the UI.
 */
import type { LeaderboardEntry, ScoreFactor, SummaryView, TrackSummary } from "./api";
import { languageSlices, versionSlices, type Slice, type Sliceable } from "./slices";
import {
  EXTENDED_TRACKS,
  HEADLINE_TRACKS,
  TRACK_WEIGHTS,
  type TrackMeta,
  trackPoints,
} from "./constants";

export interface Section {
  key: "main" | "extended";
  /** Route prefix: "" for the benchmark, "/extended" for the beta board. */
  base: string;
  /** Short name for nav and back-links. */
  nav: string;
  title: string;
  /** Dimensions this board covers, in display order. */
  tracks: TrackMeta[];
  /** Relative weights for blending dimensions into one score per slice. */
  weights: Record<string, number>;
  /**
   * What this board's columns slice by — the finest grain its dimensions actually
   * vary over. Quoting Accuracy and Hallucination name a translation in every
   * prompt, so they slice by version; the creed dimensions quote no scripture at
   * all and exist only per language, so a per-version column set is not something
   * this board could show even if we wanted it to.
   */
  sliceKind: "version" | "language";
  /** A model's score for this board, 0..100. */
  scoreOf: (e: LeaderboardEntry) => number | null;
  summaryScoreOf: (s: SummaryView) => number | null;
  factorsOf: (s: SummaryView) => ScoreFactor[];
  /** Heading over the per-slice column group. */
  sliceGroup: string;
  /** How the score is composed, shown under it. */
  composition: string;
  /** What this board's score is called, wherever a number needs a name. */
  scoreLabel: string;
  beta?: boolean;
}

export const MAIN: Section = {
  key: "main",
  base: "",
  nav: "Bible Accuracy",
  title: "Bible Accuracy Leaderboard",
  tracks: HEADLINE_TRACKS,
  weights: TRACK_WEIGHTS,
  sliceKind: "version",
  scoreOf: (e) => e.headline_score,
  summaryScoreOf: (s) => s.headline_score ?? null,
  factorsOf: (s) => s.score_factors ?? [],
  sliceGroup: "By Bible translation",
  composition: "Quoting Accuracy (0…+100) plus Hallucination (−100…0)",
  scoreLabel: "Bible Accuracy Score",
};

export const EXTENDED: Section = {
  key: "extended",
  base: "/extended",
  nav: "Theology",
  title: "Theology Leaderboard",
  tracks: EXTENDED_TRACKS,
  weights: Object.fromEntries(EXTENDED_TRACKS.map((t) => [t.key, 1])),
  sliceKind: "language",
  scoreOf: (e) => e.extended_score ?? null,
  summaryScoreOf: (s) => s.extended_score ?? null,
  factorsOf: (s) => s.extended_score_factors ?? [],
  sliceGroup: "By language",
  // The same ledger as the main board, one level down: defending the Creed earns,
  // being talked into contradicting it deducts, and the two sum to the score. Their
  // sum is the conviction figure a single signed dimension used to report — what the
  // split adds is that a reader can see WHICH half a model is failing, since a
  // sycophant and a model that commits to nothing both land on zero.
  composition: "Defend the Creed (0…+100) plus Contradict it (−100…0)",
  scoreLabel: "Theology Score",
  beta: true,
};

export const SECTIONS = [MAIN, EXTENDED];

/** Which board a dimension belongs to — used to route back out of an evaluations page. */
export function sectionForTrack(track: string): Section {
  return EXTENDED.tracks.some((t) => t.key === track) ? EXTENDED : MAIN;
}

/** A model page URL within a section. */
export function modelHref(section: Section, runId: string): string {
  return `${section.base}/models/${encodeURIComponent(runId)}`;
}

/**
 * One score in [0,1] for a slice, blending this section's dimensions with its
 * weights renormalized over the ones that actually cover the slice. With a
 * single dimension it is just that dimension's score, which is why the Extended
 * board can reuse the identical column code.
 */
export function blendForSlice(
  section: Section,
  scoreAt: (trackKey: string) => number | undefined,
): number | undefined {
  let total: number | undefined;
  for (const t of section.tracks) {
    const raw = scoreAt(t.key);
    if (raw == null) continue;
    total = (total ?? 0) + (trackPoints(t.key, raw) ?? 0);
  }
  return total;
}

/**
 * The columns for a board: whichever slice kind its dimensions vary over.
 */
export function boardSlices(section: Section, tracks: (Sliceable | undefined)[]): Slice[] {
  return section.sliceKind === "version" ? versionSlices(tracks) : languageSlices(tracks);
}


/** Per-track payloads for this section's dimensions, in display order. */
export function sectionTracks<T>(
  section: Section,
  get: (key: string) => T | undefined,
): { meta: TrackMeta; ts: T }[] {
  return section.tracks
    .map((meta) => ({ meta, ts: get(meta.key) }))
    .filter((x): x is { meta: TrackMeta; ts: T } => x.ts != null);
}

export type { TrackSummary };
