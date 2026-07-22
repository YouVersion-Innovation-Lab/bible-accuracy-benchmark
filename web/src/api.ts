// Typed client for the public results API.

export interface LeaderboardEntry {
  run_id: string;
  model_label: string;
  provider_host: string;
  run_date: string;
  headline_score: number | null;
  by_track: Record<string, number>;
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
  grades?: Record<string, number>;
  verbatim_rate?: number;
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

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  leaderboard: () => get<Leaderboard>("/api/leaderboard"),
  run: (id: string) => get<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  failures: (id: string, track: string, language: string | null, offset: number) => {
    const p = new URLSearchParams({ track, offset: String(offset), limit: "25" });
    if (language) p.set("language", language);
    return get<FailuresPage>(`/api/runs/${encodeURIComponent(id)}/failures?${p}`);
  },
};

export const SCOPE_NOTE =
  "This benchmark scores only the Biblical accuracy of scripture quotations in " +
  "model responses. It does not score or rate the theological positions or " +
  "theological accuracy of responses.";
