import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry, type VersionScore } from "../api";
import { ErrorMsg, Loading, ScoreBadge } from "../components";
import { heatColor, langName, orderLanguages } from "../constants";
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
  const [filterLang, setFilterLang] = useState<string | null>(null);
  const [filterVersion, setFilterVersion] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<string>(HEADLINE);

  const languages = useMemo(() => {
    if (!data) return [];
    const tags = new Set<string>();
    data.entries.forEach((e) => Object.keys(e.by_language || {}).forEach((t) => tags.add(t)));
    return orderLanguages([...tags]);
  }, [data]);

  // version_id -> {abbrev, language} (union across models; scores read per-model).
  const versionsByLang = useMemo(() => {
    const map = new Map<string, VersionScore[]>();
    if (!data) return map;
    const seen = new Set<number>();
    data.entries.forEach((e) =>
      (e.versions || []).forEach((v) => {
        if (seen.has(v.version_id)) return;
        seen.add(v.version_id);
        const arr = map.get(v.language_tag) || [];
        arr.push(v);
        map.set(v.language_tag, arr);
      }),
    );
    return map;
  }, [data]);

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
        label: vers.length > 1 ? `${langName(filterLang)} overall` : langName(filterLang),
        title:
          vers.length > 1 ? "Average across all versions in this language" : undefined,
        get: (e) => e.by_language?.[filterLang],
      };
      // A single-version language: the "overall" already is that version — no
      // point in a redundant duplicate column.
      if (vers.length <= 1) return [overall];
      return [overall, ...vers.map((v) => verCol(filterLang, v.version_id, v.version_abbrev))];
    }
    return languages.map((lang) => ({
      key: `lang:${lang}`,
      label: langName(lang),
      get: (e: LeaderboardEntry) => e.by_language?.[lang],
    }));
  }, [filterLang, filterVersion, languages, versionsByLang]);

  const rows = useMemo(() => {
    if (!data) return [];
    const col = cols.find((c) => c.key === sortKey);
    const val = (e: LeaderboardEntry) =>
      sortKey === HEADLINE || !col ? (e.headline_score ?? -1) : (col.get(e) ?? -1) * 100;
    return [...data.entries].sort((a, b) => val(b) - val(a));
  }, [data, cols, sortKey]);

  function chooseLang(lang: string | null) {
    setFilterLang(lang);
    setFilterVersion(null);
    setSortKey(lang ? `lang:${lang}` : HEADLINE);
  }
  function chooseVersion(vid: number | null) {
    setFilterVersion(vid);
    setSortKey(vid != null ? `ver:${vid}` : filterLang ? `lang:${filterLang}` : HEADLINE);
  }

  const langVersions = filterLang ? versionsByLang.get(filterLang) || [] : [];

  return (
    <div>
      <section className="mb-8 max-w-3xl">
        <h1 className="text-3xl font-bold mb-3">How accurately do LLMs quote the Bible?</h1>
        <p className="text-slate-300 leading-relaxed">
          Every score is produced by deterministic comparison against the actual verse text of the
          cited translation — never by an AI judge. The headline is an overall Bible Accuracy Score;
          the columns show how faithfully each model quotes scripture in each language.
        </p>
      </section>

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && data.entries.length === 0 && (
        <p className="text-slate-400">No published results yet.</p>
      )}

      {data && data.entries.length > 0 && (
        <>
          <LeaderCards entries={data.entries} languages={languages} />

          <div className="mt-8 flex flex-wrap items-end gap-4">
            <label className="text-sm">
              <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Language</div>
              <select
                className="bg-white/[0.06] border border-white/10 rounded-md px-3 py-1.5 text-sm min-w-44"
                value={filterLang ?? ""}
                onChange={(ev) => chooseLang(ev.target.value || null)}
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
              <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">
                Bible version
              </div>
              <select
                className="bg-white/[0.06] border border-white/10 rounded-md px-3 py-1.5 text-sm min-w-44 disabled:opacity-40"
                value={filterVersion ?? ""}
                disabled={!filterLang || langVersions.length <= 1}
                onChange={(ev) =>
                  chooseVersion(ev.target.value ? Number(ev.target.value) : null)
                }
              >
                <option value="">All versions</option>
                {langVersions.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.version_abbrev}
                  </option>
                ))}
              </select>
            </label>
            {(filterLang || filterVersion != null) && (
              <button
                className="text-xs text-slate-400 hover:text-white underline pb-2"
                onClick={() => chooseLang(null)}
              >
                Clear filters
              </button>
            )}
          </div>

          <div className="mt-4 overflow-x-auto rounded-xl border border-white/10">
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
                    label="Bible Accuracy"
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
            Click a column header to sort, or filter by language and Bible version above. Cells show
            direct-quote accuracy (0–100); the Bible Accuracy Score also folds in topical quoting and
            misquote resistance. Grey = not run for that model.
          </p>
        </>
      )}
    </div>
  );
}

function verCol(lang: string, versionId: number, abbrev?: string): Col {
  return {
    key: `ver:${versionId}`,
    label: abbrev || `#${versionId}`,
    title: `${langName(lang)} · ${abbrev || versionId}`,
    get: (e) => e.versions?.find((v) => v.version_id === versionId)?.score,
  };
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

function LeaderCards({
  entries,
  languages,
}: {
  entries: LeaderboardEntry[];
  languages: string[];
}) {
  const best = [...entries].sort((a, b) => (b.headline_score ?? 0) - (a.headline_score ?? 0))[0];
  const mostResistant = [...entries].sort(
    (a, b) => (b.by_track?.adversarial ?? 0) - (a.by_track?.adversarial ?? 0),
  )[0];
  // Consistent across languages = highest median language score (robust to a
  // few zero-scoring languages that every model has).
  const widest = [...entries].sort(
    (a, b) => medianLang(b, languages) - medianLang(a, languages),
  )[0];

  const cards = [
    { title: "Most accurate overall", e: best, val: best?.headline_score, suffix: "" },
    {
      title: "Most resistant to misquoting",
      e: mostResistant,
      val: (mostResistant?.by_track?.adversarial ?? 0) * 100,
      suffix: "",
    },
    {
      title: "Most consistent across languages",
      e: widest,
      val: medianLang(widest, languages),
      suffix: " median",
    },
  ];
  return (
    <div className="grid sm:grid-cols-3 gap-4">
      {cards.map((c) => (
        <div key={c.title} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div className="text-xs text-slate-400 uppercase tracking-wide">{c.title}</div>
          {c.e ? (
            <>
              <Link
                to={`/models/${encodeURIComponent(c.e.run_id)}`}
                className="text-lg font-semibold hover:underline block mt-1"
              >
                {c.e.model_label}
              </Link>
              <div className="text-2xl font-bold tabular-nums mt-1">
                {c.val != null ? c.val.toFixed(1) : "—"}
                <span className="text-sm text-slate-500">{c.suffix}</span>
              </div>
            </>
          ) : (
            <div className="text-slate-500 mt-2">—</div>
          )}
        </div>
      ))}
    </div>
  );
}

function medianLang(e: LeaderboardEntry | undefined, languages: string[]): number {
  if (!e) return 0;
  const vals = languages
    .map((l) => e.by_language?.[l])
    .filter((v): v is number => v != null)
    .map((v) => v * 100)
    .sort((a, b) => a - b);
  if (!vals.length) return 0;
  const mid = Math.floor(vals.length / 2);
  return vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
}
