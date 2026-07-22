// Shared Language + Bible-version filter, used by the leaderboard, model
// detail, and failure browser. Versions are language-specific, so the version
// selector is scoped to (and disabled outside of) the chosen language.
import type { VersionScore } from "./api";
import { langName } from "./constants";

export type VersionsByLang = Map<string, VersionScore[]>;

/** Group a flat list of version scores by language, de-duping by version_id. */
export function buildVersionsByLang(versions: VersionScore[]): VersionsByLang {
  const map: VersionsByLang = new Map();
  const seen = new Set<number>();
  for (const v of versions) {
    if (seen.has(v.version_id)) continue;
    seen.add(v.version_id);
    const arr = map.get(v.language_tag) ?? [];
    arr.push(v);
    map.set(v.language_tag, arr);
  }
  return map;
}

/** Human label for the active slice, e.g. "English · KJV" or "Spanish". */
export function sliceLabel(lang: string | null, versionAbbrev?: string): string {
  if (!lang) return "overall";
  return versionAbbrev ? `${langName(lang)} · ${versionAbbrev}` : langName(lang);
}

const SELECT_CLS =
  "bg-white/[0.06] border border-white/10 rounded-md px-3 py-1.5 text-sm min-w-44 disabled:opacity-40";

export function FilterBar({
  languages,
  versionsByLang,
  lang,
  version,
  onLang,
  onVersion,
  versionEnabled = true,
}: {
  languages: string[];
  versionsByLang: VersionsByLang;
  lang: string | null;
  version: number | null;
  onLang: (l: string | null) => void;
  onVersion: (v: number | null) => void;
  versionEnabled?: boolean;
}) {
  const langVersions = lang ? (versionsByLang.get(lang) ?? []) : [];
  const versionDisabled = !versionEnabled || !lang || langVersions.length <= 1;
  return (
    <div className="flex flex-wrap items-end gap-4">
      <label className="text-sm">
        <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Language</div>
        <select
          className={SELECT_CLS}
          value={lang ?? ""}
          onChange={(e) => onLang(e.target.value || null)}
        >
          <option value="">All languages</option>
          {languages.map((l) => (
            <option key={l} value={l}>
              {langName(l)}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Bible version</div>
        <select
          className={SELECT_CLS}
          value={version ?? ""}
          disabled={versionDisabled}
          onChange={(e) => onVersion(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">All versions</option>
          {langVersions.map((v) => (
            <option key={v.version_id} value={v.version_id}>
              {v.version_abbrev}
            </option>
          ))}
        </select>
      </label>
      {(lang || version != null) && (
        <button
          className="text-xs text-slate-400 hover:text-white underline pb-2"
          onClick={() => onLang(null)}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
