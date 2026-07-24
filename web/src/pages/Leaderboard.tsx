import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry } from "../api";
import { ErrorMsg, Loading, ScoreBadge } from "../components";
import { TRACK_WEIGHTS, heatColor, langName, orderLanguages } from "../constants";
import { useFilters } from "../filterContext";
import { useAsync } from "../hooks";

// A data column in the matrix: a value in [0,1] per model, or undefined if the
// model wasn't scored on it.
interface Col {
  key: string;
  label: string;
  title?: string;
  get: (e: LeaderboardEntry) => number | undefined;
}

const HEADLINE = "headline";

export function Leaderboard() {
  const { data, error, loading } = useAsync(() => api.leaderboard(), []);
  // Language + version come from the global (header) filter.
  const { lang: filterLang, version: filterVersion, versionsByLang } = useFilters();
  const [sortKey, setSortKey] = useState<string>(HEADLINE);
  const [benchVer, setBenchVer] = useState<string | null>(null);

  // Benchmark generations present in the data, newest first. The board shows one
  // generation at a time (rankings stay apples-to-apples); default to the newest.
  const benchVersions = useMemo(() => {
    if (!data) return [];
    const s = new Set(data.entries.map((e) => e.run_version).filter((v): v is string => !!v));
    return [...s].sort((a, b) => verNum(b) - verNum(a));
  }, [data]);
  const activeVer = benchVer ?? benchVersions[0] ?? null;

  const entries = useMemo(
    () => (data ? data.entries.filter((e) => !activeVer || e.run_version === activeVer) : []),
    [data, activeVer],
  );

  const languages = useMemo(() => {
    const tags = new Set<string>();
    entries.forEach((e) => Object.keys(e.by_language || {}).forEach((t) => tags.add(t)));
    return orderLanguages([...tags]);
  }, [entries]);

  // The Overall Score column itself reflects the active slice, so default to
  // sorting by it whenever the filter changes.
  useEffect(() => {
    setSortKey(HEADLINE);
  }, [filterLang, filterVersion]);

  // Data columns beside the (filter-aware) Overall Score column.
  const cols: Col[] = useMemo(() => {
    // A specific version: the Overall Score column already shows that version's
    // slice, so there's nothing to add.
    if (filterVersion != null) return [];
    // A language: one single-verse (direct-quote) column per version of that
    // language. The blended overall for the language is the Overall Score
    // column, so we don't repeat it as its own column.
    if (filterLang) {
      return (versionsByLang.get(filterLang) || []).map((v) =>
        verCol(filterLang, v.version_id, v.version_abbrev),
      );
    }
    // No filter: one Overall Score column per language.
    return languages.map((lang) => ({
      key: `lang:${lang}`,
      label: langName(lang),
      title: `Overall score for ${langName(lang)}`,
      get: (e: LeaderboardEntry) => overallForLang(e, lang),
    }));
  }, [filterLang, filterVersion, languages, versionsByLang]);

  // The model's Overall Score for the current slice (0..100): the headline when
  // unfiltered, else the blended overall restricted to the language/version.
  const overallScore = (e: LeaderboardEntry): number | null => {
    if (!filterLang) return e.headline_score;
    const v = overallForSlice(e, filterLang, filterVersion);
    return v == null ? null : v * 100;
  };

  const rows = useMemo(() => {
    const col = cols.find((c) => c.key === sortKey);
    const val = (e: LeaderboardEntry) => {
      if (sortKey !== HEADLINE && col) return (col.get(e) ?? -1) * 100;
      return overallScore(e) ?? -1;
    };
    return [...entries].sort((a, b) => val(b) - val(a));
  }, [entries, cols, sortKey, filterLang, filterVersion]);

  return (
    <div>
      <section className="mb-8 max-w-3xl text-slate-300 leading-relaxed space-y-4">
        <h1 className="text-3xl font-bold text-white">How accurately do LLMs quote the Bible?</h1>
        <p>
          A public, deterministic benchmark of how faithfully LLMs quote the Bible — for the teams
          building them, and for anyone choosing a model to trust with Scripture.
        </p>
        <div>
          <p>
            Every quote is checked character-by-character against the real verse — never by an AI
            judge — across ~28 languages and dozens of translations. Three dimensions:
          </p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>
              <strong>Direct Quotation</strong> — asked for a specific verse, does it reproduce the
              exact text?
            </li>
            <li>
              <strong>Scripture in Answers</strong> — answering a real question, are the verses it
              quotes accurate?
            </li>
            <li>
              <strong>Hallucination Resistance</strong> — asked for a verse that doesn't exist, does
              it decline or invent one?
            </li>
          </ul>
          <p className="mt-2">
            Accurate, willing quotation scores high; misquotes, invented verses, and refusing to
            quote when a quote is warranted score low.
          </p>
        </div>
        <p>We hope it's a helpful contribution to the work of building and using LLMs well.</p>
      </section>

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && data.entries.length === 0 && (
        <p className="text-slate-400">No published results yet.</p>
      )}

      {data && data.entries.length > 0 && (
        <>
          <div className="mb-4 flex items-center gap-2 text-sm">
            <span className="text-xs uppercase tracking-wide text-slate-500">
              Benchmark version
            </span>
            {benchVersions.length > 1 ? (
              <select
                className="bg-white/[0.06] border border-white/10 rounded px-2 py-1 text-sm"
                value={activeVer ?? ""}
                onChange={(e) => setBenchVer(e.target.value)}
              >
                {benchVersions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                    {v === benchVersions[0] ? " (latest)" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-medium">{activeVer ?? "—"}</span>
            )}
            <Link to="/methodology" className="text-xs text-slate-400 hover:underline">
              what this version tests →
            </Link>
          </div>

          <div className="mt-6 overflow-x-auto rounded-xl border border-white/10">
            <table className="text-sm border-collapse">
              <thead className="bg-white/[0.04] text-slate-300">
                <tr>
                  <th className="sticky left-0 z-20 bg-[#11162a] text-left font-medium px-3 py-3 w-8">
                    #
                  </th>
                  <th className="sticky left-8 z-20 bg-[#11162a] text-left font-medium px-3 py-3 min-w-56">
                    Model
                  </th>
                  <SortableTh
                    label="Overall Score"
                    title={
                      filterLang
                        ? "Overall score for the current filter"
                        : "Overall score across all languages"
                    }
                    active={sortKey === HEADLINE}
                    onClick={() => setSortKey(HEADLINE)}
                  />
                  {cols.map((c) => (
                    <SortableTh
                      key={c.key}
                      label={c.label}
                      title={c.title}
                      active={sortKey === c.key}
                      onClick={() => setSortKey(c.key)}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((e, i) => (
                  <tr key={e.run_id} className="border-t border-white/5">
                    <td className="sticky left-0 z-10 bg-[#0b1020] px-3 py-3 text-slate-500 tabular-nums">
                      {i + 1}
                    </td>
                    <td className="sticky left-8 z-10 bg-[#0b1020] px-3 py-3">
                      <Link
                        to={`/models/${encodeURIComponent(e.run_id)}`}
                        className="font-medium hover:underline"
                      >
                        {e.model_label}
                      </Link>
                      <div className="text-xs text-slate-500">
                        {e.provider_host}
                        {e.run_version ? ` · ${e.run_version}` : ""}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <ScoreBadge score={overallScore(e)} />
                    </td>
                    {cols.map((c) => (
                      <HeatCell key={c.key} value={c.get(e)} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Overall Score blends single-verse accuracy (50%), topical-quote accuracy (25%), and
            hallucination resistance (25%), and always reflects the current filter. With no filter,
            each language column is that language's Overall Score; choose a language to break it out
            by Bible version (single-verse, character-by-character accuracy). Grey = not run. Click a
            header to sort.
          </p>
        </>
      )}
    </div>
  );
}

// Numeric ordering for benchmark version strings like "v0.2" / "v1.10".
function verNum(v: string): number {
  const [maj = 0, min = 0] = v.replace(/^v/i, "").split(".").map(Number);
  return maj * 1000 + min;
}

// A single Bible version's single-verse (direct-quote) accuracy column.
function verCol(lang: string, versionId: number, abbrev?: string): Col {
  return {
    key: `ver:${versionId}`,
    label: abbrev || `#${versionId}`,
    title: `Single-verse quote accuracy · ${langName(lang)} · ${abbrev || versionId}`,
    get: (e) => e.versions?.find((v) => v.version_id === versionId)?.score,
  };
}

// A model's blended Overall Score (0..1) for one language: the same weighted
// mix as the headline (50% single-verse / 25% topical / 25% hallucination),
// renormalized over the tracks that cover this language. Falls back to
// single-verse accuracy when per-track detail isn't present.
function overallForLang(e: LeaderboardEntry, lang: string): number | undefined {
  const td = e.tracks_detail;
  if (!td) return e.by_language?.[lang];
  let num = 0;
  let den = 0;
  for (const [track, w] of Object.entries(TRACK_WEIGHTS)) {
    const v = td[track]?.by_language?.[lang];
    if (v != null) {
      num += w * v;
      den += w;
    }
  }
  return den > 0 ? num / den : e.by_language?.[lang];
}

// Overall Score (0..1) for the active slice. A language slice blends by-language
// track scores; a specific version blends the per-version track scores (only the
// tracks that were run in that version contribute), matching the model-detail
// page. Falls back to the single-verse score when per-track detail is absent.
function overallForSlice(
  e: LeaderboardEntry,
  lang: string,
  version: number | null,
): number | undefined {
  if (version == null) return overallForLang(e, lang);
  const single = e.versions?.find((v) => v.version_id === version)?.score;
  const td = e.tracks_detail;
  if (!td) return single;
  let num = 0;
  let den = 0;
  for (const [track, w] of Object.entries(TRACK_WEIGHTS)) {
    const v = td[track]?.versions?.find((x) => x.version_id === version)?.score;
    if (v != null) {
      num += w * v;
      den += w;
    }
  }
  return den > 0 ? num / den : single;
}

function SortableTh({
  label,
  active,
  onClick,
  title,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <th
      onClick={onClick}
      className={`px-3 py-3 text-center font-medium cursor-pointer whitespace-nowrap hover:text-white ${
        active ? "text-white" : ""
      }`}
      title={title ? `${title} — sort` : `Sort by ${label}`}
    >
      {label} {active ? "▼" : ""}
    </th>
  );
}

function HeatCell({ value }: { value: number | undefined }) {
  const { bg, fg } = heatColor(value);
  return (
    <td className="px-3 py-3 text-center tabular-nums" style={{ background: bg, color: fg }}>
      {value == null ? "—" : (value * 100).toFixed(0)}
    </td>
  );
}
