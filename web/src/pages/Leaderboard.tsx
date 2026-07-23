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

  // Follow the global filter: sort by the active version, else language, else overall.
  useEffect(() => {
    setSortKey(
      filterVersion != null
        ? `ver:${filterVersion}`
        : filterLang
          ? `lang:${filterLang}`
          : HEADLINE,
    );
  }, [filterLang, filterVersion]);

  // The data columns depend on the active filter.
  const cols: Col[] = useMemo(() => {
    if (filterLang && filterVersion != null) {
      const v = versionsByLang.get(filterLang)?.find((x) => x.version_id === filterVersion);
      return [verCol(filterLang, filterVersion, v?.version_abbrev)];
    }
    if (filterLang) {
      const vers = versionsByLang.get(filterLang) || [];
      const overall: Col = {
        key: `lang:${filterLang}`,
        label: "Overall",
        title: `Overall score (blended across tracks) for ${langName(filterLang)}`,
        get: (e) => overallForLang(e, filterLang),
      };
      // Single-version language: a per-version column would just duplicate the
      // one version every track used, so show only the blended Overall.
      if (vers.length <= 1) return [overall];
      return [overall, ...vers.map((v) => verCol(filterLang, v.version_id, v.version_abbrev))];
    }
    return languages.map((lang) => ({
      key: `lang:${lang}`,
      label: langName(lang),
      title: `Overall score for ${langName(lang)}`,
      get: (e: LeaderboardEntry) => overallForLang(e, lang),
    }));
  }, [filterLang, filterVersion, languages, versionsByLang]);

  const rows = useMemo(() => {
    const col = cols.find((c) => c.key === sortKey);
    const val = (e: LeaderboardEntry) =>
      sortKey === HEADLINE || !col ? (e.headline_score ?? -1) : (col.get(e) ?? -1) * 100;
    return [...entries].sort((a, b) => val(b) - val(a));
  }, [entries, cols, sortKey]);

  return (
    <div>
      <section className="mb-8 max-w-3xl">
        <h1 className="text-3xl font-bold mb-3">How accurately do LLMs quote the Bible?</h1>
        <p className="text-slate-300 leading-relaxed">
          We built this benchmark to give the teams developing LLMs a public, objective measure of
          how faithfully their models handle the actual words of the Bible — and to help the many
          people who turn to LLMs for Scripture choose the model that best fits their need for
          Biblical accuracy. Every score is produced deterministically: each quotation is compared
          character-by-character against the real verse in the cited translation, never judged by
          another AI, across roughly 28 languages and dozens of Bible versions.{" "}
          <strong>Direct Quotation</strong> asks for a specific verse in a named translation and
          measures how exactly the model reproduces the real text.{" "}
          <strong>Scripture in Answers</strong> poses genuine questions like “What does the Bible say
          about anxiety?” and checks whether the verses the model chooses to quote are accurate.{" "}
          <strong>Hallucination Resistance</strong> asks for references that do not exist (such as
          “Psalm 180:1”) and rewards the model for saying so rather than inventing a verse. A model
          scores well by quoting Scripture accurately and willingly — word-for-word, in whatever
          language and translation it is asked. It scores poorly for misquoting a verse, fabricating
          text for a passage that isn't real, or refusing to quote when a direct quotation is exactly
          what the question calls for. We hope this proves a genuinely useful contribution to the
          exciting, fast-moving work of building and using LLMs well.
        </p>
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
                    title="Overall score across all languages"
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
                      <ScoreBadge score={e.headline_score} />
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
            Each cell is a model's Overall Score (0–100) for that language: 50% single-verse quote
            accuracy + 25% topical-quote accuracy + 25% hallucination resistance (renormalized over
            the tracks that cover the language). Select a Bible version to see literal single-verse
            (character-by-character) accuracy for that version instead. Grey = not run for that
            model. Click a header to sort.
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
