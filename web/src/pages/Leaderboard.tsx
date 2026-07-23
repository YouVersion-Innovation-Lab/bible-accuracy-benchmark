import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry } from "../api";
import { ErrorMsg, Loading, ScoreBadge } from "../components";
import { TRACK_WEIGHTS, heatColor, langName, orderLanguages } from "../constants";
import { FilterBar, buildVersionsByLang, sliceLabel, type VersionsByLang } from "../FilterBar";
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
  const versionsByLang = useMemo(
    () => buildVersionsByLang(data ? data.entries.flatMap((e) => e.versions ?? []) : []),
    [data],
  );

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

  return (
    <div>
      <section className="mb-8 max-w-3xl">
        <h1 className="text-3xl font-bold mb-3">How accurately do LLMs quote the Bible?</h1>
        <p className="text-slate-300 leading-relaxed">
          Every score is deterministic: the model's text is compared against the actual verse in the
          cited translation — no AI judge is involved. The <strong>Overall Score</strong> column is
          each model's weighted result across all languages; every other cell is that model's Overall
          Score for one language — a blend of single-verse quote accuracy (50%), accuracy of verses
          quoted in topical answers (25%), and resistance to quoting verses that don't exist (25%).
        </p>
      </section>

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && data.entries.length === 0 && (
        <p className="text-slate-400">No published results yet.</p>
      )}

      {data && data.entries.length > 0 && (
        <>
          <LeaderCards
            entries={data.entries}
            languages={languages}
            versionsByLang={versionsByLang}
            filterLang={filterLang}
            filterVersion={filterVersion}
          />

          <div className="mt-8">
            <FilterBar
              languages={languages}
              versionsByLang={versionsByLang}
              lang={filterLang}
              version={filterVersion}
              onLang={chooseLang}
              onVersion={chooseVersion}
            />
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

interface CardSpec {
  title: string;
  e?: LeaderboardEntry;
  val: number | undefined;
  suffix?: string;
  sub?: string;
}

// Score (0..1) for the active slice: a specific version's single-verse accuracy,
// else a language's blended Overall Score, else the model's overall headline.
function sliceScore(
  e: LeaderboardEntry,
  lang: string | null,
  version: number | null,
): number | undefined {
  if (version != null) return e.versions?.find((v) => v.version_id === version)?.score;
  if (lang) return overallForLang(e, lang);
  return e.headline_score == null ? undefined : e.headline_score / 100;
}

// Landing view (no filter): the three headline dimensions of the benchmark.
function overallCards(entries: LeaderboardEntry[], languages: string[]): CardSpec[] {
  const best = [...entries].sort((a, b) => (b.headline_score ?? 0) - (a.headline_score ?? 0))[0];
  const mostResistant = [...entries].sort(
    (a, b) => (b.by_track?.phantom ?? 0) - (a.by_track?.phantom ?? 0),
  )[0];
  // Robust to the few zero-scoring languages every model has.
  const widest = [...entries].sort(
    (a, b) => medianLang(b, languages) - medianLang(a, languages),
  )[0];
  return [
    { title: "Highest overall score", e: best, val: best?.headline_score ?? undefined },
    {
      title: "Most resistant to hallucination",
      e: mostResistant,
      val: (mostResistant?.by_track?.phantom ?? 0) * 100,
    },
    {
      title: "Most consistent across languages",
      e: widest,
      val: medianLang(widest, languages),
      suffix: " median",
    },
  ];
}

// Filtered view: best / field average / lowest for the exact slice, so the
// cards show the actual numbers behind the current language + version.
function sliceCards(
  entries: LeaderboardEntry[],
  lang: string,
  version: number | null,
  versionsByLang: VersionsByLang,
): CardSpec[] {
  const abbrev =
    version != null
      ? versionsByLang.get(lang)?.find((v) => v.version_id === version)?.version_abbrev
      : undefined;
  const label = sliceLabel(lang, abbrev);
  // A version slice is literal single-verse accuracy; a language slice is the
  // blended Overall Score.
  const metric = version != null ? "single-verse" : "overall";
  const scored = entries
    .map((e) => ({ e, v: sliceScore(e, lang, version) }))
    .filter((x): x is { e: LeaderboardEntry; v: number } => x.v != null)
    .sort((a, b) => b.v - a.v);
  if (!scored.length) return [{ title: `Highest ${metric} · ${label}`, val: undefined }];

  const avg = scored.reduce((s, x) => s + x.v, 0) / scored.length;
  const cards: CardSpec[] = [
    { title: `Highest ${metric} · ${label}`, e: scored[0].e, val: scored[0].v * 100 },
    {
      title: `Field average · ${label}`,
      val: avg * 100,
      sub: `across ${scored.length} model${scored.length > 1 ? "s" : ""}`,
    },
  ];
  if (scored.length > 1) {
    const worst = scored[scored.length - 1];
    cards.push({ title: `Lowest ${metric} · ${label}`, e: worst.e, val: worst.v * 100 });
  }
  return cards;
}

function LeaderCards({
  entries,
  languages,
  versionsByLang,
  filterLang,
  filterVersion,
}: {
  entries: LeaderboardEntry[];
  languages: string[];
  versionsByLang: VersionsByLang;
  filterLang: string | null;
  filterVersion: number | null;
}) {
  const cards = filterLang
    ? sliceCards(entries, filterLang, filterVersion, versionsByLang)
    : overallCards(entries, languages);
  return (
    <div className="grid sm:grid-cols-3 gap-4">
      {cards.map((c) => (
        <div key={c.title} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div className="text-xs text-slate-400 uppercase tracking-wide">{c.title}</div>
          {c.e ? (
            <Link
              to={`/models/${encodeURIComponent(c.e.run_id)}`}
              className="text-lg font-semibold hover:underline block mt-1"
            >
              {c.e.model_label}
            </Link>
          ) : (
            <div className="text-lg font-semibold mt-1 text-slate-300">{c.sub ?? " "}</div>
          )}
          <div className="text-2xl font-bold tabular-nums mt-1">
            {c.val != null ? c.val.toFixed(1) : "—"}
            {c.suffix ? <span className="text-sm text-slate-500">{c.suffix}</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

// Median of a model's per-language Overall Scores — a breadth measure that a few
// zero-scoring languages can't dominate.
function medianLang(e: LeaderboardEntry | undefined, languages: string[]): number {
  if (!e) return 0;
  const vals = languages
    .map((l) => overallForLang(e, l))
    .filter((v): v is number => v != null)
    .map((v) => v * 100)
    .sort((a, b) => a - b);
  if (!vals.length) return 0;
  const mid = Math.floor(vals.length / 2);
  return vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
}
