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
import { EXTENDED_TRACKS, HEADLINE_TRACKS, TRACK_WEIGHTS, type TrackMeta } from "./constants";

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
  /** Which dimension supplies the per-translation columns. */
  versionTrack: string;
  /** A model's score for this board, 0..100. */
  scoreOf: (e: LeaderboardEntry) => number | null;
  summaryScoreOf: (s: SummaryView) => number | null;
  factorsOf: (s: SummaryView) => ScoreFactor[];
  /** Heading over the blended-per-language column group. */
  langGroup: string;
  /** Heading over the per-translation column group. */
  verGroup: string;
  /** How the score is composed, shown under it. */
  composition: string;
  beta?: boolean;
}

export const MAIN: Section = {
  key: "main",
  base: "",
  nav: "Leaderboard",
  title: "Bible Accuracy Benchmark",
  tracks: HEADLINE_TRACKS,
  weights: TRACK_WEIGHTS,
  versionTrack: "simple",
  scoreOf: (e) => e.headline_score,
  summaryScoreOf: (s) => s.headline_score ?? null,
  factorsOf: (s) => s.score_factors ?? [],
  langGroup: "Overall by language",
  verGroup: "Overall by translation",
  composition: "67% Direct Quotation · 33% Hallucination Resistance",
};

export const EXTENDED: Section = {
  key: "extended",
  base: "/extended",
  nav: "Extended Benchmark",
  title: "Extended Benchmark — Beta",
  tracks: EXTENDED_TRACKS,
  weights: Object.fromEntries(EXTENDED_TRACKS.map((t) => [t.key, 1])),
  versionTrack: "topical",
  scoreOf: (e) => e.extended_score ?? null,
  summaryScoreOf: (s) => s.extended_score ?? null,
  factorsOf: (s) => s.extended_score_factors ?? [],
  langGroup: "Extended by language",
  verGroup: "Scripture in Answers by translation",
  // Each extended dimension keeps its own 100-point scale rather than being
  // blended — they measure unrelated things, and averaging them would produce a
  // number that means nothing in particular.
  composition: "Scripture in Answers · Basic Christian Theology, each scored separately",
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
  let num = 0;
  let den = 0;
  for (const t of section.tracks) {
    const v = scoreAt(t.key);
    const w = section.weights[t.key] ?? 0;
    if (v != null) {
      num += w * v;
      den += w;
    }
  }
  return den > 0 ? num / den : undefined;
}

/**
 * Whether per-translation columns tell you anything the per-language columns
 * don't. They only do when some language was tested on more than one
 * translation — otherwise every translation column is its language's column
 * under a different heading, and showing both invites the reader to look for a
 * difference that cannot exist.
 *
 * True for Direct Quotation (English alone has five editions); false for the
 * open-question dimensions, which define one translation per language.
 */
export function versionColumnsInform(langCount: number, versionCount: number): boolean {
  return versionCount > langCount;
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
