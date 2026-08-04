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
  composition: "Quoting Accuracy (0…+100) plus Hallucination (−100…0)",
};

export const EXTENDED: Section = {
  key: "extended",
  base: "/extended",
  nav: "Extended Benchmark",
  title: "Extended Benchmark — Beta",
  tracks: EXTENDED_TRACKS,
  weights: Object.fromEntries(EXTENDED_TRACKS.map((t) => [t.key, 1])),
  // Neither creed dimension mentions a translation — they quote no scripture at
  // all — so this names one of them deliberately: it carries no version slices,
  // which suppresses the per-translation block rather than borrowing a quoting
  // dimension's translations onto a board they have nothing to do with.
  versionTrack: "creed_defend",
  scoreOf: (e) => e.extended_score ?? null,
  summaryScoreOf: (s) => s.extended_score ?? null,
  factorsOf: (s) => s.extended_score_factors ?? [],
  langGroup: "Extended by language",
  verGroup: "Extended by translation",
  // The same ledger as the main board, one level down: defending the Creed earns,
  // being talked into contradicting it deducts, and the two sum to the score. Their
  // sum is the conviction figure a single signed dimension used to report — what the
  // split adds is that a reader can see WHICH half a model is failing, since a
  // sycophant and a model that commits to nothing both land on zero.
  composition: "Defend the Creed (0…+100) plus Contradict it (−100…0)",
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
