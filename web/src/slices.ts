// Slices of a run's results — a whole language, or one Bible version of one
// language — plus the URLs that open the raw test cases behind a slice.
//
// The site has no filter state: every page renders every slice it has data for,
// and a slice is only ever *navigated to* (as query params on the evaluations
// URL), so a drilled-down view is shareable and the back button works.
import type { VersionScore } from "./api";
import { langName, orderLanguages } from "./constants";

/**
 * The shape every per-track payload shares — TrackSummary on a run page,
 * TrackDetail on the leaderboard. Only these two fields carry slice scores.
 */
export interface Sliceable {
  by_language?: Record<string, number>;
  versions?: VersionScore[];
}

export interface Slice {
  key: string; // "lang:eng" | "ver:111"
  lang: string;
  versionId: number | null;
  label: string; // "English" | "NIV11 (English)"
}

export function langSlice(lang: string): Slice {
  return { key: `lang:${lang}`, lang, versionId: null, label: langName(lang) };
}

export function versionSlice(v: VersionScore): Slice {
  const abbrev = v.version_abbrev || `#${v.version_id}`;
  return {
    key: `ver:${v.version_id}`,
    lang: v.language_tag,
    versionId: v.version_id,
    label: `${abbrev} (${langName(v.language_tag)})`,
  };
}

/** Every language any of these tracks scored, in canonical order. */
export function languageSlices(tracks: (Sliceable | undefined)[]): Slice[] {
  const tags = new Set<string>();
  for (const ts of tracks) Object.keys(ts?.by_language ?? {}).forEach((t) => tags.add(t));
  return orderLanguages([...tags]).map(langSlice);
}

/**
 * Every Bible version any of these tracks scored, deduped by version_id and
 * ordered by language (canonical) then abbreviation, so columns group by
 * language without needing a spanning header.
 */
export function versionSlices(tracks: (Sliceable | undefined)[]): Slice[] {
  const byId = new Map<number, VersionScore>();
  for (const ts of tracks) {
    for (const v of ts?.versions ?? []) if (!byId.has(v.version_id)) byId.set(v.version_id, v);
  }
  const langs = orderLanguages([...new Set([...byId.values()].map((v) => v.language_tag))]);
  const slices = [...byId.values()]
    .sort(
      (a, b) =>
        langs.indexOf(a.language_tag) - langs.indexOf(b.language_tag) ||
        (a.version_abbrev || "").localeCompare(b.version_abbrev || ""),
    )
    .map(versionSlice);
  // Two editions recorded under one abbreviation would render as two identical
  // headings — indistinguishable, and no clue which column is which. Name the
  // edition ID so they can be told apart.
  const seen = new Map<string, number>();
  for (const s of slices) seen.set(s.label, (seen.get(s.label) ?? 0) + 1);
  return slices.map((s) =>
    (seen.get(s.label) ?? 0) > 1 && s.versionId != null
      ? { ...s, label: s.label.replace(" (", ` #${s.versionId} (`) }
      : s,
  );
}

/** A track's score (0..1) for one slice, or undefined if it wasn't scored there. */
export function sliceScore(ts: Sliceable | undefined, s: Slice): number | undefined {
  if (!ts) return undefined;
  if (s.versionId != null) return ts.versions?.find((v) => v.version_id === s.versionId)?.score;
  return ts.by_language?.[s.lang];
}

/** URL for the raw test cases of one dimension, optionally narrowed to a slice. */
export function evalHref(runId: string, track: string, s?: Slice | null): string {
  const base = `/models/${encodeURIComponent(runId)}/evaluations/${track}`;
  if (!s) return base;
  const p = new URLSearchParams({ language: s.lang });
  if (s.versionId != null) p.set("version_id", String(s.versionId));
  return `${base}?${p}`;
}
