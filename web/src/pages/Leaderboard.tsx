import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry } from "../api";
import { ErrorMsg, HeatCell, Loading, ScoreBadge } from "../components";
import { TRACKS, TRACK_WEIGHTS } from "../constants";
import { useAsync } from "../hooks";
import { languageSlices, sliceScore, versionSlices, type Slice } from "../slices";

// A data column in the matrix: a value in [0,1] per model, or undefined if the
// model wasn't scored on it.
interface Col {
  key: string;
  label: string;
  title?: string;
  first?: boolean; // starts a column group — gets a divider
  get: (e: LeaderboardEntry) => number | undefined;
}

const HEADLINE = "headline";

export function Leaderboard() {
  const { data, error, loading } = useAsync(() => api.leaderboard(), []);
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

  // Every language and every Bible version in this generation, always all shown:
  // no filter to set, nothing hidden behind one.
  const cols: Col[] = useMemo(() => {
    const langs = languageSlices(
      entries.flatMap((e) => TRACKS.map((t) => e.tracks_detail?.[t.key])),
    );
    const versions = versionSlices(
      entries.map((e) => e.tracks_detail?.simple ?? { versions: e.versions }),
    );
    return [
      ...langs.map((s, i) => ({
        key: s.key,
        label: s.label,
        title: `Overall score for ${s.label} — all three dimensions`,
        first: i === 0,
        get: (e: LeaderboardEntry) => overallForLang(e, s.lang),
      })),
      ...versions.map((s, i) => ({
        key: s.key,
        label: s.label,
        title: `Direct Quotation accuracy · ${s.label}`,
        first: i === 0,
        get: (e: LeaderboardEntry) => quoteScore(e, s),
      })),
    ];
  }, [entries]);

  const nLang = useMemo(() => cols.filter((c) => c.key.startsWith("lang:")).length, [cols]);

  const rows = useMemo(() => {
    const col = cols.find((c) => c.key === sortKey);
    const val = (e: LeaderboardEntry) =>
      sortKey !== HEADLINE && col ? (col.get(e) ?? -1) * 100 : (e.headline_score ?? -1);
    return [...entries].sort((a, b) => val(b) - val(a));
  }, [entries, cols, sortKey]);

  return (
    <div>
      <section className="mb-8 text-slate-300 leading-normal space-y-3">
        <h1 className="text-3xl font-bold text-white">How accurately do LLMs quote the Bible?</h1>
        <div>
          <p>
            A public, deterministic benchmark of how faithfully LLMs quote the Bible. Three dimensions:
          </p>
          <ul className="list-disc pl-5 mt-1 space-y-0.5">
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
          <p className="mt-1">
            Accurate, willing quotation scores high; misquotes, invented verses, and refusing to
            quote when a quote is warranted score low.
          </p>
        </div>
        <p className="text-slate-400">
          This benchmark rates only the accuracy of quoted scripture — it does not score or rate the
          theological positions or theological accuracy of a response.
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

          <p className="text-xs text-slate-500 mb-2">
            Every language and every translation tested, all shown at once — scroll sideways for the
            rest. Click a column heading to sort by it, or a model to see its own breakdown.
            <span className="block mt-1">
              <span className="text-slate-400">By language</span> blends all three dimensions
              (50% Direct Quotation · 25% Scripture in Answers · 25% Hallucination Resistance).{" "}
              <span className="text-slate-400">By translation</span> shows Direct Quotation only —
              it is the one dimension whose prompts name a translation.
            </span>
          </p>

          <div className="mt-3 overflow-x-auto rounded-xl border border-white/10">
            <table className="text-sm border-collapse">
              <thead className="bg-white/[0.04] text-slate-300">
                <tr>
                  <th
                    rowSpan={2}
                    className="sticky left-0 z-20 bg-[#11162a] text-left font-medium px-3 py-3 w-8"
                  >
                    #
                  </th>
                  <th
                    rowSpan={2}
                    className="sticky left-8 z-20 bg-[#11162a] text-left font-medium px-3 py-3 min-w-56"
                  >
                    Model
                  </th>
                  <SortableTh
                    label="Overall Score"
                    title="Overall score across every language"
                    active={sortKey === HEADLINE}
                    onClick={() => setSortKey(HEADLINE)}
                    rowSpan={2}
                  />
                  <GroupTh span={nLang} label="Overall by language" />
                  <GroupTh span={cols.length - nLang} label="Direct Quotation by translation" />
                </tr>
                <tr>
                  {cols.map((c) => (
                    <SortableTh
                      key={c.key}
                      label={c.label}
                      title={c.title}
                      active={sortKey === c.key}
                      onClick={() => setSortKey(c.key)}
                      divider={c.first}
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
                      <HeatCell
                        key={c.key}
                        value={c.get(e)}
                        title={`${e.model_label} · ${c.title ?? c.label}`}
                        divider={c.first}
                      />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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

// Direct-quote accuracy (0..1) for one translation.
function quoteScore(e: LeaderboardEntry, s: Slice): number | undefined {
  return sliceScore(e.tracks_detail?.simple ?? { versions: e.versions }, s);
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

// Heading over a block of columns. The label is sticky *inside* its own span, so
// it stays readable while you scroll through a block 18 columns wide instead of
// sitting centred somewhere off-screen.
function GroupTh({ span, label }: { span: number; label: string }) {
  return (
    <th
      colSpan={span}
      className="px-3 pt-2 pb-1 text-left font-medium border-l border-white/10"
    >
      <span className="sticky left-[17rem] inline-block text-[11px] uppercase tracking-wide text-slate-500">
        {label}
      </span>
    </th>
  );
}

function SortableTh({
  label,
  active,
  onClick,
  title,
  rowSpan,
  divider,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  title?: string;
  rowSpan?: number;
  divider?: boolean;
}) {
  return (
    <th
      onClick={onClick}
      rowSpan={rowSpan}
      className={`px-3 py-3 text-center font-medium cursor-pointer whitespace-nowrap hover:text-white ${
        active ? "text-white" : ""
      } ${divider ? "border-l border-white/10" : ""}`}
      title={title ? `${title} — sort` : `Sort by ${label}`}
    >
      {label} {active ? "▼" : ""}
    </th>
  );
}
