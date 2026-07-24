// Typed client for the public results API.

export interface VersionScore {
  version_id: number;
  language_tag: string;
  version_abbrev: string;
  score: number; // 0..1
  n: number;
}

export interface VersionPreference {
  by_version: Record<string, number>; // version_id -> quote count
  top_version_id: number;
  n: number;
}

// Per-(language, version) slice of one track, for the site's filters.
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

export interface Summary {
  headline_score: number;
  headline_partial?: boolean;
  by_track: Record<string, number>;
  tracks: Record<string, TrackSummary>;
  usage?: Record<string, number>;
  scoring_scope_note?: string;
}

export interface TrackSummary {
  track_score: number;
  n?: number;
  by_language?: Record<string, number>;
  by_tier?: Record<string, number>;
  by_version?: Record<string, number>;
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
  emission_rate_by_level?: Record<string, number>;
  sensitive_topic_score?: number | null;
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
  items: FailureItem[];
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
