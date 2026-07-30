import { Link, useParams } from "react-router-dom";
import { api, type TrackSummary } from "../api";
import { BetaNotice, HeatCell, Loading, ScoreBadge } from "../components";
import { DimensionBreakdown } from "../dimensionDetail";
import { useAsync } from "../hooks";
import {
  EXTENDED,
  MAIN,
  blendForSlice,
  modelHref,
  sectionTracks,
  versionColumnsInform,
  type Section,
} from "../sections";
import { ScoreFactors } from "../scoreFactors";
import { evalHref, languageSlices, sliceScore, versionSlices, type Slice } from "../slices";

export function Report({ section }: { section: Section }) {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);

  if (loading) return <Loading />;
  if (error)
    return (
      <div className="space-y-3">
        <Link to={section.base || "/"} className="text-sm text-slate-400 hover:underline">
          ← {section.nav}
        </Link>
        <p className="text-slate-300">
          This model's results aren't available right now — the run may have been re-run or
          unpublished since the leaderboard was built. Head back to the leaderboard for the
          current results.
        </p>
      </div>
    );
  if (!data) return null;

  const s = data.summary;
  const tracks = s.tracks;
  const present = sectionTracks(section, (k) => tracks[k]);

  if (present.length === 0)
    return (
      <div className="space-y-3">
        <Link to={section.base || "/"} className="text-sm text-slate-400 hover:underline">
          ← {section.nav}
        </Link>
        <p className="text-slate-300">
          This run has no {section.beta ? "Extended Benchmark" : "scored"} results — it was
          evaluated without {section.tracks.map((t) => t.name).join(" or ")}.
        </p>
      </div>
    );

  const trackList = present.map((p) => p.ts);
  // Every language and every Bible version this section covered. No filters:
  // both tables always show everything, and a cell is the way into its subset.
  const langCols = languageSlices(trackList);
  const allVerCols = versionSlices(trackList);
  // Only worth its own table when some language carries more than one edition;
  // otherwise it restates the language table under different headings.
  const verCols = versionColumnsInform(langCols.length, allVerCols.length) ? allVerCols : [];
  const scoreAt = (slice: Slice) => (k: string) => sliceScore(tracks[k], slice);

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <Link to={section.base || "/"} className="text-sm text-slate-400 hover:underline">
            ← {section.nav}
          </Link>
          <h1 className="text-3xl font-bold mt-1">{data.model.label}</h1>
          <p className="text-slate-500 text-sm">
            {data.model.model}
            {data.model.base_url_host ? ` · ${data.model.base_url_host}` : ""}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-400 uppercase tracking-wide">
            {section.beta ? "Extended Score" : "Overall Score"}
          </div>
          <div className="text-3xl font-bold mt-1">
            <ScoreBadge score={section.summaryScoreOf(s)} />
          </div>
          <div className="text-xs text-slate-500 mt-1">{section.composition}</div>
          {s.headline_partial && !section.beta && (
            <div className="text-xs text-amber-400 mt-1">partial (not all dimensions run)</div>
          )}
        </div>
      </div>

      {section.beta && <BetaNotice />}

      <ScoreFactors factors={section.factorsOf(s)} score={section.summaryScoreOf(s)} />

      <div>
        <h2 className="text-lg font-semibold mb-1">What we measured</h2>
        <p className="text-xs text-slate-500 mb-3">
          {present.length === 1 ? "This dimension" : "Each dimension"} scored across every language
          and translation tested.
        </p>
        <div className={`grid gap-4 ${present.length > 1 ? "sm:grid-cols-2" : ""}`}>
          {present.map(({ meta, ts }) => (
            <div key={meta.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-semibold">{meta.name}</h3>
                <span className="text-2xl font-bold tabular-nums">
                  {ts.track_score != null ? (ts.track_score * 100).toFixed(1) : "—"}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                {ts.n != null ? `${ts.n.toLocaleString()} test cases` : "all languages"}
                {section.weights[meta.key] != null && present.length > 1 && (
                  <> · {weightPct(section, meta.key)} of the score</>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-2 mb-3 leading-relaxed">{meta.blurb}</p>
              <Link
                to={evalHref(runId, meta.key)}
                className="text-xs text-indigo-300 hover:underline"
              >
                Browse evaluations →
              </Link>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold mb-1">Where the score comes from</h2>
          <p className="text-xs text-slate-500">
            Every test case is recorded with the specific outcome it earned, not just
            pass/fail — inventing a verse, quoting the right verse from the wrong
            translation, and quoting a real verse without citing it are different
            behaviours worth different amounts. Counts below are for the whole run.
          </p>
        </div>
        {present.map(({ meta, ts }) => (
          <div key={meta.key} className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
            <div className="flex items-baseline justify-between gap-3 mb-4">
              <h3 className="font-semibold">{meta.name}</h3>
              <Link
                to={evalHref(runId, meta.key)}
                className="text-xs text-indigo-300 hover:underline"
              >
                Browse every test case →
              </Link>
            </div>
            <DimensionBreakdown trackKey={meta.key} ts={ts} />
          </div>
        ))}
      </div>

      {langCols.length > 0 && (
        <SliceTable
          runId={runId}
          section={section}
          heading="Scores by language"
          note={
            present.length > 1
              ? "Click any score to read the test cases behind it. The Overall row blends both dimensions, the same way the leaderboard does."
              : "Click any score to read the test cases behind it. Nothing here asks for a particular translation, so there is one column per language; each quotation is checked against every translation of its language, and each test case names the one it matched."
          }
          tracks={tracks}
          cols={langCols}
          overall={present.length > 1 ? (c) => blendForSlice(section, scoreAt(c)) : undefined}
        />
      )}

      {verCols.length > 0 && (
        <SliceTable
          runId={runId}
          section={section}
          heading="Scores by Bible translation"
          note={
            present.length > 1
              ? "Only Direct Quotation names a translation in its prompt, so it is the one dimension scored on every translation. The other asks for a reference that doesn't exist, so each language contributes a single column — the translation its prompts were built from."
              : "No translation is requested — the question is open — so each language contributes a single column: the translation its prompts were built from. Quotations themselves are checked against every translation of the language."
          }
          tracks={tracks}
          cols={verCols}
        />
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <Link to="/methodology" className="text-slate-400 hover:underline">
          How scoring works →
        </Link>
        <Link
          to={modelHref(section.key === "main" ? EXTENDED : MAIN, runId)}
          className="text-indigo-300 hover:underline"
        >
          {section.key === "main"
            ? "This model on the Extended Benchmark (beta) →"
            : "← This model on the scored benchmark"}
        </Link>
      </div>
    </div>
  );
}

function weightPct(section: Section, key: string): string {
  const total = Object.values(section.weights).reduce((a, b) => a + b, 0);
  return `${Math.round((100 * (section.weights[key] ?? 0)) / total)}%`;
}

// One dimension × slice heat matrix. Every populated cell links to the raw test
// cases for exactly that (dimension, slice) subset.
function SliceTable({
  runId,
  section,
  heading,
  note,
  tracks,
  cols,
  overall,
}: {
  runId: string;
  section: Section;
  heading: string;
  note: string;
  tracks: Record<string, TrackSummary>;
  cols: Slice[];
  overall?: (s: Slice) => number | undefined;
}) {
  const present = sectionTracks(section, (k) => tracks[k]);
  return (
    <div>
      <h2 className="text-lg font-semibold mb-1">{heading}</h2>
      <p className="text-xs text-slate-500 mb-3">{note}</p>
      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="text-sm border-collapse">
          <thead className="bg-white/[0.04] text-slate-300">
            <tr>
              <th className="sticky left-0 z-20 bg-[#11162a] text-left font-medium px-3 py-3 min-w-56">
                Dimension
              </th>
              {cols.map((c) => (
                <th key={c.key} className="px-3 py-3 text-center font-medium whitespace-nowrap">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {present.map(({ meta, ts }) => (
              <tr key={meta.key} className="border-t border-white/5">
                <td className="sticky left-0 z-10 bg-[#0b1020] px-3 py-3">
                  <Link to={evalHref(runId, meta.key)} className="font-medium hover:underline">
                    {meta.name}
                  </Link>
                </td>
                {cols.map((c) => (
                  <HeatCell
                    key={c.key}
                    value={sliceScore(ts, c)}
                    title={`${meta.name} · ${c.label} — read these test cases`}
                    href={evalHref(runId, meta.key, c)}
                  />
                ))}
              </tr>
            ))}
            {overall && (
              <tr className="border-t border-white/10 bg-white/[0.02]">
                <td className="sticky left-0 z-10 bg-[#11162a] px-3 py-3 font-medium">
                  Overall (both dimensions)
                </td>
                {cols.map((c) => (
                  <HeatCell key={c.key} value={overall(c)} title={`Overall score · ${c.label}`} />
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ModelDetail() {
  return <Report section={MAIN} />;
}

export function ExtendedModelDetail() {
  return <Report section={EXTENDED} />;
}
