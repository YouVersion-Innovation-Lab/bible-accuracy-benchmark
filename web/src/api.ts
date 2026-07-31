// Typed client for the public results API.

export interface VersionScore {
  version_id: number;
  language_tag: string;
  version_abbrev: string;
  score: number; // 0..1 — every book this edition was asked about
  n: number;
  // Which canons that turned out to include, and how it did on each. A Catholic
  // or Orthodox edition carries books a Protestant one doesn't, which is why two
  // editions can differ in item count; both are scored on what they carry.
  canon_profile?: string[];
  by_canon?: Record<string, number>;
  canon_counts?: Record<string, number>;
}

export interface VersionPreference {
  by_version: Record<string, number>; // version_id -> quote count
  top_version_id: number;
  n: number;
}

// Per-(language, version) slice of one track — the leaderboard's columns.
export interface TrackDetail {
  track_score: number | null;
  by_language: Record<string, number>;
  versions: VersionScore[];
  version_preference?: Record<string, VersionPreference>; // topical only
}

export interface LeaderboardEntry {
  run_id: string;
  run_version: string | null;
  model_label: string;
  model_id: string;
  provider_host: string;
  run_date: string;
  headline_score: number | null;
  // Score for the Extended Benchmark (beta) dimensions, on their own 0-100
  // scale. Deliberately not folded into headline_score.
  extended_score?: number | null;
  by_track: Record<string, number>;
  by_language: Record<string, number>;
  versions: VersionScore[];
  tracks_detail?: Record<string, TrackDetail>;
  fabrication_rate: number | null;
  refusal_rate: number | null;
}

export interface Leaderboard {
  scope_note: string;
  entries: LeaderboardEntry[];
}

export interface RunDetail {
  scope_note: string;
  run_id: string;
  model: { label: string; base_url_host?: string; model?: string };
  summary: Summary;
}

// One named cause of lost points, for the "what dropped this score" panel.
// Points are off a 100-point scale and sum to (100 - headline_score).
export interface ScoreFactor {
  track: string;
  key: string;
  points: number;
  n: number;
}

/**
 * Everything a score display needs. The run summary is one of these, and so is
 * each per-translation slice — identical shape on purpose, so filtering the
 * model page to a translation is a matter of reading a different object rather
 * than recomputing anything in the browser.
 */
export interface SummaryView {
  headline_score: number;
  headline_partial?: boolean;
  score_factors?: ScoreFactor[];
  headline_tracks?: string[];
  extended_tracks?: string[];
  extended_score?: number | null;
  extended_score_factors?: ScoreFactor[];
  by_track: Record<string, number>;
  tracks: Record<string, TrackSummary>;
}

/** One Bible translation's slice of a run, scored by the same aggregation. */
export interface SummarySlice extends SummaryView {
  version_id: number;
  language_tag: string;
  version_abbrev: string;
  /** Dimensions this slice narrowed to the translation itself. */
  translation_scoped: string[];
  /** Dimensions that name no translation, so they narrowed to its language. */
  language_scoped: string[];
}

export interface Summary extends SummaryView {
  slices?: SummarySlice[];
  usage?: Record<string, number>;
  scoring_scope_note?: string;
}

export interface TrackSummary {
  track_score: number;
  n?: number;
  by_language?: Record<string, number>;
  by_tier?: Record<string, number>;
  by_version?: Record<string, number>;
  // Canon slices — descriptive, not a filter. Every book an edition carries is
  // scored, so these answer "is this model worse on the deuterocanon?" rather
  // than marking which books count.
  by_canon?: Record<string, number>;
  canon_counts?: Record<string, number>;
  canon_languages?: Record<string, string[]>;
  // Per-dimension loss attribution; summed and reweighted into Summary.score_factors.
  score_factors?: { key: string; points: number; n: number }[];
  versions?: VersionScore[];
  version_preference?: Record<string, VersionPreference>;
  grades?: Record<string, number>;
  // phantom (hallucination) track
  by_kind?: Record<string, number>;
  hallucination_rate?: number;
  misattribution_rate?: number;
  substitute_rate?: number;
  outcomes?: Record<string, number>;
  verbatim_rate?: number;
  near_verbatim_rate?: number;
  fabrication_rate?: number;
  refusal_rate?: number;
  wrong_version_rate?: number;
  other_language_rate?: number;
  emission_rate_by_level?: Record<string, number>;
  by_level?: Record<string, number>;
  by_topic?: Record<string, number>;
  sensitive_topic_score?: number | null;
  nonsensitive_topic_score?: number | null;
  fabricated_ref_count?: number;
  fabricated_quote_count?: number;
  other_language_quote_count?: number;
  quote_provenance?: Record<string, number>;
  misquoted_quote_count?: number;
  quote_grades?: Record<string, number>;
  n_quotes?: number;
  unreferenced_rate?: number;
  no_response_rate?: number;
  format_ok_rate?: number;
  resistance_at_1?: number;
  resistance_at_3?: number;
  correction_rate?: number;
  by_category?: Record<string, number>;
}

export interface FailureItem {
  id: string;
  prompt?: string;
  passed?: boolean;
  language_tag?: string;
  version_abbrev?: string;
  reference?: string;
  usfm?: string;
  grade?: string;
  score?: number;
  qer?: number;
  response_text?: string;
  expected_text?: string;
  // topical
  topic_name?: string;
  elicitation_level?: string;
  sensitive?: boolean;
  quotes?: { classification: string; quote: string; cited_usfm?: string }[];
  // phantom (hallucination)
  kind?: string;
  outcome?: string;
  // adversarial
  category?: string;
  target_usfm?: string;
  attacker?: string;
  reasons?: string[];
}

/** One quote span the auditor found and verified. */
export interface QuoteVerdict {
  quote: string;
  classification: string;
  similarity: number;
  matched_usfm?: string | null;
  cited_usfm?: string | null;
  score: number;
  matched_version_id?: number | null;
  unquoted?: boolean;
}

/** Metadata about the model call itself. */
export interface CallMeta {
  finish_reason?: string | null;
  refusal?: string | null;
  model_served?: string | null;
  provider?: string | null;
  response_id?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  reasoning_tokens?: number | null;
  error?: string | null;
}

/**
 * One scored test case with the FULL deterministic scoring detail, so the site
 * can show how the score was derived instead of just asserting it.
 */
export interface EvalItem {
  id: string;
  prompt?: string;
  response_text?: string;
  passed?: boolean;
  language_tag?: string;
  version_abbrev?: string;
  version_id?: number;
  score?: number;
  call?: CallMeta;

  // ---- Direct Quotation ----
  reference?: string;
  usfm?: string;
  tier?: string;
  canon?: string;
  grade?: string;
  qer?: number;
  wer?: number | null;
  expected_text?: string;
  verbatim_strict?: boolean;
  verbatim_loose?: boolean;
  format_ok?: boolean;
  overquote?: boolean;
  extraction_method?: string;
  edit_ops?: { insert?: number; delete?: number; replace?: number };
  best_distractor?: { key: string; similarity: number } | null;
  best_neighbor?: { usfm: string; similarity: number } | null;
  ground_truth_drift?: boolean;
  scoring_version?: string;

  // ---- Scripture in Answers ----
  topic_id?: string;
  topic_name?: string;
  elicitation_level?: string;
  sensitive?: boolean;
  accuracy?: number | null;
  emission?: number;
  n_quotes?: number;
  n_accurate?: number;
  n_fabricated?: number;
  n_misquote?: number;
  n_fabricated_refs?: number;
  grades?: Record<string, number>;
  quotes?: QuoteVerdict[];
  cited_refs?: string[];
  fabricated_refs?: string[];

  // ---- Hallucination Resistance ----
  kind?: string;
  outcome?: string;
  denial_signaled?: boolean;
  // kind === "absent_from_version" only: the reference is a real verse, carried
  // by absent_source_abbrev but not by the translation we asked.
  absent_usfm?: string;
  absent_source_abbrev?: string;
}

export interface FailuresPage {
  total: number;
  offset: number;
  limit: number;
  track: string;
  items: FailureItem[];
}

export interface EvaluationsPage {
  total: number;
  n_pass: number;
  n_fail: number;
  offset: number;
  limit: number;
  track: string;
  outcome: string;
  items: EvalItem[];
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  leaderboard: () => get<Leaderboard>("/api/leaderboard"),
  run: (id: string) => get<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  failures: (
    id: string,
    track: string,
    language: string | null,
    offset: number,
    versionId?: number | null,
  ) => {
    const p = new URLSearchParams({ track, offset: String(offset), limit: "25" });
    if (language) p.set("language", language);
    if (versionId != null) p.set("version_id", String(versionId));
    return get<FailuresPage>(`/api/runs/${encodeURIComponent(id)}/failures?${p}`);
  },
  evaluations: (
    id: string,
    track: string,
    outcome: string,
    language: string | null,
    versionId: number | null,
    offset: number,
  ) => {
    const p = new URLSearchParams({ track, outcome, offset: String(offset), limit: "25" });
    if (language) p.set("language", language);
    if (versionId != null) p.set("version_id", String(versionId));
    return get<EvaluationsPage>(`/api/runs/${encodeURIComponent(id)}/evaluations?${p}`);
  },
};

export const SCOPE_NOTE =
  "This benchmark scores only the Biblical accuracy of scripture quotations in " +
  "model responses. It does not score or rate the theological positions or " +
  "theological accuracy of responses.";
