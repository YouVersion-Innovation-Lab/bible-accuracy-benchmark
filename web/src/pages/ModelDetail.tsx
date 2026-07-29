import { Link, useParams } from "react-router-dom";
import { api, type TrackSummary } from "../api";
import { HeatCell, Loading, ScoreBadge } from "../components";
import { TRACK_WEIGHTS, TRACKS } from "../constants";
import { DimensionBreakdown } from "../dimensionDetail";
import { ScoreFactors } from "../scoreFactors";
import { useAsync } from "../hooks";
import { evalHref, languageSlices, sliceScore, versionSlices, type Slice } from "../slices";

export function ModelDetail() {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);

  if (loading) return <Loading />;
  if (error)
    return (
      <div className="space-y-3">
        <Link to="/" className="text-sm text-slate-400 hover:underline">
          ← Leaderboard
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
  const present = TRACKS.filter((t) => tracks[t.key]);
  const trackList = present.map((t) => tracks[t.key]);

  // Every language and every Bible version this run covered. No filters: both
  // tables always show everything, and a cell is the way into its own subset.
  const langCols = languageSlices(trackList);
  const verCols = versionSlices(trackList);

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <Link to="/" className="text-sm text-slate-400 hover:underline">
            ← Leaderboard
          </Link>
          <h1 className="text-3xl font-bold mt-1">{data.model.label}</h1>
          <p className="text-slate-500 text-sm">
            {data.model.model}
            {data.model.base_url_host ? ` · ${data.model.base_url_host}` : ""}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-400 uppercase tracking-wide">Overall Score</div>
          <div className="text-3xl font-bold mt-1">
            <ScoreBadge score={s.headline_score ?? null} />
          </div>
          <div className="text-xs text-slate-500 mt-1">
            50% single-verse · 25% topical · 25% hallucination
          </div>
          {s.headline_partial && (
            <div className="text-xs text-amber-400 mt-1">partial (not all tracks run)</div>
          )}
        </div>
      </div>

      <ScoreFactors summary={s} />

      <div>
        <h2 className="text-lg font-semibold mb-1">What we measured</h2>
        <p className="text-xs text-slate-500 mb-3">
          Each dimension scored across every language and translation tested.
        </p>
        <div className="grid sm:grid-cols-3 gap-4">
          {present.map((t) => {
            const ts = tracks[t.key];
            return (
              <div key={t.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="font-semibold">{t.name}</h3>
                  <span className="text-2xl font-bold tabular-nums">
                    {ts.track_score != null ? (ts.track_score * 100).toFixed(1) : "—"}
                  </span>
                </div>
                <div className="text-xs text-slate-500">
                  {ts.n != null ? `${ts.n.toLocaleString()} test cases` : "all languages"}
                </div>
                <p className="text-xs text-slate-400 mt-2 mb-3 leading-relaxed">{t.blurb}</p>
                <Link
                  to={evalHref(runId, t.key)}
                  className="text-xs text-indigo-300 hover:underline"
                >
                  Browse evaluations →
                </Link>
              </div>
            );
          })}
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
        {present.map((t) => (
          <div key={t.key} className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
            <div className="flex items-baseline justify-between gap-3 mb-4">
              <h3 className="font-semibold">{t.name}</h3>
              <Link
                to={evalHref(runId, t.key)}
                className="text-xs text-indigo-300 hover:underline"
              >
                Browse every test case →
              </Link>
            </div>
            <DimensionBreakdown trackKey={t.key} ts={tracks[t.key]} />
          </div>
        ))}
      </div>

      {langCols.length > 0 && (
        <SliceTable
          runId={runId}
          heading="Scores by language"
          note="Click any score to read the test cases behind it. The Overall row blends all three dimensions, the same way the leaderboard does."
          tracks={tracks}
          cols={langCols}
          overall={(s2) => overallForSlice(tracks, s2)}
        />
      )}

      {verCols.length > 0 && (
        <SliceTable
          runId={runId}
          heading="Scores by Bible translation"
          note="Only Direct Quotation names a translation in its prompt, so it is the one dimension scored on every translation. The other two ask open questions, so each language contributes a single column — the translation its prompts were built from."
          tracks={tracks}
          cols={verCols}
        />
      )}

      <Link to="/methodology" className="inline-block text-sm text-slate-400 hover:underline">
        How scoring works →
      </Link>
    </div>
  );
}

// One dimension × slice heat matrix. Every populated cell links to the raw test
// cases for exactly that (dimension, slice) subset.
function SliceTable({
  runId,
  heading,
  note,
  tracks,
  cols,
  overall,
}: {
  runId: string;
  heading: string;
  note: string;
  tracks: Record<string, TrackSummary>;
  cols: Slice[];
  overall?: (s: Slice) => number | undefined;
}) {
  const present = TRACKS.filter((t) => tracks[t.key]);
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
            {present.map((t) => (
              <tr key={t.key} className="border-t border-white/5">
                <td className="sticky left-0 z-10 bg-[#0b1020] px-3 py-3">
                  <Link to={evalHref(runId, t.key)} className="font-medium hover:underline">
                    {t.name}
                  </Link>
                </td>
                {cols.map((c) => (
                  <HeatCell
                    key={c.key}
                    value={sliceScore(tracks[t.key], c)}
                    title={`${t.name} · ${c.label} — read these test cases`}
                    href={evalHref(runId, t.key, c)}
                  />
                ))}
              </tr>
            ))}
            {overall && (
              <tr className="border-t border-white/10 bg-white/[0.02]">
                <td className="sticky left-0 z-10 bg-[#11162a] px-3 py-3 font-medium">
                  Overall (all three)
                </td>
                {cols.map((c) => (
                  <HeatCell
                    key={c.key}
                    value={overall(c)}
                    title={`Overall score · ${c.label}`}
                  />
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// The headline blend (50/25/25) restricted to one slice and renormalized over
// the dimensions that cover it — matching the leaderboard's language columns.
function overallForSlice(
  tracks: Record<string, TrackSummary>,
  slice: Slice,
): number | undefined {
  let num = 0;
  let den = 0;
  for (const [key, w] of Object.entries(TRACK_WEIGHTS)) {
    const v = sliceScore(tracks[key], slice);
    if (v != null) {
      num += w * v;
      den += w;
    }
  }
  return den > 0 ? num / den : undefined;
}
