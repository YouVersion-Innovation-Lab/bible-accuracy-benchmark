import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry } from "../api";
import { BetaNotice, ErrorMsg, HeatCell, Loading, ScoreBadge } from "../components";
import { useAsync } from "../hooks";
import {
  EXTENDED,
  MAIN,
  blendForSlice,
  modelHref,
  versionColumnsInform,
  type Section,
} from "../sections";
import { languageSlices, sliceScore, versionSlices } from "../slices";

// A data column in the matrix: a value in [0,1] per model, or undefined if the
// model wasn't scored on it.
interface Col {
  key: string;
  label: string;
  title?: string;
  first?: boolean; // starts a column group — gets a divider
  get: (e: LeaderboardEntry) => number | undefined;
}

const OVERALL = "overall";

export function Board({ section }: { section: Section }) {
  const { data, error, loading } = useAsync(() => api.leaderboard(), []);
  const [sortKey, setSortKey] = useState<string>(OVERALL);
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

  // Every language and every Bible version this section covers, always all
  // shown: no filter to set, nothing hidden behind one.
  const cols: Col[] = useMemo(() => {
    const langs = languageSlices(
      entries.flatMap((e) => section.tracks.map((t) => e.tracks_detail?.[t.key])),
    );
    const allVersions = versionSlices(entries.map((e) => e.tracks_detail?.[section.versionTrack]));
    // Drop the per-translation block entirely when it would just restate the
    // per-language one — 11 columns of identical numbers is noise, not detail.
    const versions = versionColumnsInform(langs.length, allVersions.length) ? allVersions : [];
    return [
      ...langs.map((s, i) => ({
        key: s.key,
        label: s.label,
        title: `${section.title} score for ${s.label}`,
        first: i === 0,
        get: (e: LeaderboardEntry) =>
          blendForSlice(section, (t) => e.tracks_detail?.[t]?.by_language?.[s.lang]),
      })),
      // Both ranked dimensions name a translation in their prompts, so a
      // translation column is the same blend as a language column — just at a
      // finer grain. It used to be Direct Quotation alone, because Hallucination
      // Resistance named no translation and had nothing to contribute here.
      ...versions.map((s, i) => ({
        key: s.key,
        label: s.label,
        title: `${section.verGroup} · ${s.label}`,
        first: i === 0,
        get: (e: LeaderboardEntry) =>
          blendForSlice(section, (t) => sliceScore(e.tracks_detail?.[t], s)),
      })),
    ];
  }, [entries, section]);

  const nLang = useMemo(() => cols.filter((c) => c.key.startsWith("lang:")).length, [cols]);

  const rows = useMemo(() => {
    const col = cols.find((c) => c.key === sortKey);
    const val = (e: LeaderboardEntry) =>
      sortKey !== OVERALL && col ? (col.get(e) ?? -1) * 100 : (section.scoreOf(e) ?? -1);
    return [...entries].sort((a, b) => val(b) - val(a));
  }, [entries, cols, sortKey, section]);

  return (
    <div>
      {section.beta ? <ExtendedIntro /> : <MainIntro />}

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

          {isFast(activeVer) && (
            <div className="mb-4 rounded-lg border border-sky-400/25 bg-sky-400/[0.06] px-4 py-3 text-sm">
              <span className="rounded bg-sky-400/15 text-sky-300 text-[10px] uppercase tracking-wide px-1.5 py-0.5 align-middle">
                fast pass
              </span>{" "}
              <span className="text-sky-100/90">
                About a tenth of the questions.
              </span>{" "}
              <span className="text-slate-400">
                Every language and every translation is still covered — the items are thinned
                within each language, not truncated — and the questions are a subset of the full
                run's, so these scores differ from a full run by coverage rather than by sample.
                Read them as a first look, not a final ranking: per-translation columns rest on
                only a handful of verses each.
              </span>
            </div>
          )}

          <p className="text-xs text-slate-500 mb-2">
            Every language and every translation tested, all shown at once — scroll sideways for the
            rest. Click a column heading to sort by it, or a model to see its own breakdown.
            <span className="block mt-1">
              {cols.length > nLang ? (
                <>
                  Both blocks are the same blend ({section.composition}) at two grains:{" "}
                  <span className="text-slate-400">by language</span>, then{" "}
                  <span className="text-slate-400">by the individual translation</span> each
                  dimension named in its prompts.
                </>
              ) : (
                <>
                  One column per language: nothing here asks for a particular translation, so
                  there is no per-translation split to show. Each quotation is checked against
                  every translation of its language.
                </>
              )}
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
                    label={section.beta ? "Extended Score" : "Overall Score"}
                    title={`${section.composition}, across every language`}
                    active={sortKey === OVERALL}
                    onClick={() => setSortKey(OVERALL)}
                    rowSpan={2}
                  />
                  <GroupTh span={nLang} label={section.langGroup} />
                  <GroupTh span={cols.length - nLang} label={section.verGroup} />
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
                      <Link to={modelHref(section, e.run_id)} className="font-medium hover:underline">
                        {e.model_label}
                      </Link>
                      <div className="text-xs text-slate-500">
                        {e.provider_host}
                        {e.run_version ? ` · ${e.run_version}` : ""}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <ScoreBadge score={section.scoreOf(e)} />
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

          <CrossLink section={section} />
        </>
      )}
    </div>
  );
}

function MainIntro() {
  return (
    <section className="mb-8 text-slate-300 leading-normal space-y-3">
      <h1 className="text-3xl font-bold text-white">How accurately do LLMs quote the Bible?</h1>
      <div>
        <p>
          A public, deterministic benchmark of how faithfully LLMs quote the Bible. Two scored
          dimensions:
        </p>
        <ul className="list-disc pl-5 mt-1 space-y-0.5">
          <li>
            <strong>Direct Quotation</strong> — asked for a specific verse, does it reproduce the
            exact text?
          </li>
          <li>
            <strong>Hallucination Resistance</strong> — asked for a verse that doesn't exist, does
            it decline or invent one?
          </li>
        </ul>
        <p className="mt-1">
          Accurate, willing quotation scores high; misquotes, invented verses, and refusing to quote
          when a quote is warranted score low.
        </p>
      </div>
      <p className="text-slate-400">
        This benchmark rates only the accuracy of quoted scripture — it does not score or rate the
        theological positions or theological accuracy of a response.
      </p>
    </section>
  );
}

function ExtendedIntro() {
  return (
    <section className="mb-8 text-slate-300 leading-normal space-y-3">
      <h1 className="text-3xl font-bold text-white">Extended Benchmark — Beta</h1>
      <BetaNotice />
      <div>
        <p>
          <strong>Scripture in Answers.</strong> The benchmark's two scored dimensions both name
          exactly what they want: a verse, or a reference that doesn't exist. This one doesn't. It
          asks an open question — “What does the Bible say about anxiety?” — and scores the accuracy
          of whatever scripture the model volunteers, if any.
        </p>
        <p className="mt-2">
          That makes it the measurement closest to how people actually use these models, and the
          hardest to score: the scorer has to find quotations nobody marked, decide which verse each
          one is, and judge it against every translation of that language. It is reported here on
          its own terms while that work settles.
        </p>
      </div>
      <p className="text-slate-400">
        Read exactly as the main board: same columns, same colours, same drill-downs. The only
        difference is that this score is not part of any model's Overall Score.
      </p>
    </section>
  );
}

function CrossLink({ section }: { section: Section }) {
  const other = section.key === "main" ? EXTENDED : MAIN;
  return (
    <div className="mt-6 rounded-xl border border-white/10 bg-white/[0.02] p-4 text-sm">
      {section.key === "main" ? (
        <>
          <Link to={other.base || "/"} className="text-indigo-300 hover:underline font-medium">
            Extended Benchmark — Beta →
          </Link>
          <p className="text-xs text-slate-500 mt-1">
            Scripture in Answers: how accurate the verses are when a model quotes scripture
            unprompted, in reply to an ordinary question. Measured on every model above, reported
            separately, and not part of any Overall Score.
          </p>
        </>
      ) : (
        <>
          <Link to="/" className="text-indigo-300 hover:underline font-medium">
            ← Back to the Bible Accuracy Benchmark
          </Link>
          <p className="text-xs text-slate-500 mt-1">
            The scored board: Direct Quotation and Hallucination Resistance, {MAIN.composition}.
          </p>
        </>
      )}
    </div>
  );
}

// Numeric ordering for benchmark version strings: "v0.2", "v1.10", "v0.5-fast".
//
// A suffixed generation sorts just BELOW its full version, because it asks a
// subset of the same questions — when both exist the full run is the better
// default. Parsing only the leading digits also matters: Number("5-fast") is NaN,
// and a NaN comparator silently leaves the list unsorted, which would have
// defaulted the board to an older generation and hidden the newest one behind
// the selector.
function verNum(v: string): number {
  const bare = v.replace(/^v/i, "");
  const m = bare.match(/^(\d+)(?:\.(\d+))?/);
  if (!m) return -1;
  const num = Number(m[1]) * 1000 + Number(m[2] ?? 0);
  return m[0] === bare ? num : num - 0.5;
}

/** Is this generation a fast pass rather than a full run? */
function isFast(v: string | null): boolean {
  return !!v && /-fast$/.test(v);
}

// Heading over a block of columns. The label is sticky *inside* its own span, so
// it stays readable while you scroll through a block 18 columns wide instead of
// sitting centred somewhere off-screen.
function GroupTh({ span, label }: { span: number; label: string }) {
  if (span <= 0) return null;
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

export function Leaderboard() {
  return <Board section={MAIN} />;
}

export function ExtendedLeaderboard() {
  return <Board section={EXTENDED} />;
}
