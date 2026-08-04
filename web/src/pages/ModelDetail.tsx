import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { BetaNotice, HeatCell, Loading, ScoreBadge } from "../components";
import { trackPoints } from "../constants";
import { useAsync } from "../hooks";
import { EXTENDED, MAIN, boardSlices, sectionTracks, type Section } from "../sections";
import { evalHref, sliceScore, type Slice } from "../slices";

/**
 * One model, one board, one table.
 *
 * Rows are the board's two dimensions in the points they contribute, so they add
 * up to the score above them. Columns are every slice those dimensions vary over —
 * Bible translations for the ranked pair, languages for the creed pair, which is
 * the finest grain the creed probes have. Every cell links to the raw test cases
 * behind it, so no number on this page is the end of the trail.
 */
export function Report({ section }: { section: Section }) {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);

  if (loading) return <Loading />;
  const summary = data?.summary;
  if (error || !summary || !data)
    return (
      <Missing section={section}>
        This model's results aren't available right now — the run may have been re-run or
        unpublished since the leaderboard was built. Head back to the leaderboard for the
        current results.
      </Missing>
    );

  const tracks = summary.tracks;
  const present = sectionTracks(section, (k) => tracks[k]);
  if (present.length === 0)
    return (
      <Missing section={section}>
        This run has no {section.title} results — it was evaluated without{" "}
        {section.tracks.map((t) => t.name).join(" or ")}.
      </Missing>
    );

  const cols = boardSlices(
    section,
    present.map((p) => p.ts),
  );

  return (
    <div className="space-y-6">
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
          <div className="text-xs text-slate-400 uppercase tracking-wide">{section.scoreLabel}</div>
          <div className="text-3xl font-bold mt-1">
            <ScoreBadge score={section.summaryScoreOf(summary)} />
          </div>
          <div className="text-xs text-slate-500 mt-1">{section.composition}</div>
        </div>
      </div>

      {section.beta && <BetaNotice />}

      <p className="text-xs text-slate-500 leading-relaxed">
        One row per dimension, in the points it contributes — the two add up to the score
        above. Columns narrow it to{" "}
        {section.sliceKind === "version" ? "a single Bible translation" : "a single language"}.{" "}
        <strong className="text-slate-300">Every cell opens the test cases behind it.</strong>{" "}
        A blank cell means that dimension wasn't measured there: seven of the eighteen editions
        carry no hallucination items, because those prompts are built from one named Bible.
      </p>

      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="min-w-full text-sm">
          <thead className="bg-white/[0.03] text-xs text-slate-400">
            <tr>
              <th className="sticky left-0 z-10 bg-[#0b1020] text-left font-medium px-3 py-2">
                Dimension
              </th>
              <th className="px-3 py-2 font-medium border-l border-white/10">All</th>
              {cols.map((c) => (
                <th key={c.key} className="px-3 py-2 font-medium whitespace-nowrap" title={c.label}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {present.map(({ meta, ts }) => (
              <tr key={meta.key} className="border-t border-white/5">
                <td className="sticky left-0 z-10 bg-[#0b1020] px-3 py-3">
                  <Link
                    to={evalHref(runId, meta.key)}
                    className="font-medium hover:underline"
                    title={meta.blurb}
                  >
                    {meta.name}
                  </Link>
                  <div className="text-xs text-slate-500">
                    {meta.polarity === "debit" ? "deducts · −100…0" : "earns · 0…+100"}
                  </div>
                </td>
                <td className="px-3 py-3 text-center border-l border-white/10">
                  <ScoreBadge
                    score={trackPoints(meta.key, ts.track_score)}
                    polarity={meta.polarity}
                  />
                </td>
                {cols.map((c: Slice) => {
                  const raw = sliceScore(ts, c);
                  return (
                    <HeatCell
                      key={c.key}
                      value={trackPoints(meta.key, raw)}
                      polarity={meta.polarity}
                      title={`${data.model.label} · ${meta.name} · ${c.label}`}
                      href={raw == null ? undefined : evalHref(runId, meta.key, c)}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Missing({ section, children }: { section: Section; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <Link to={section.base || "/"} className="text-sm text-slate-400 hover:underline">
        ← {section.nav}
      </Link>
      <p className="text-slate-300">{children}</p>
    </div>
  );
}

export function ModelDetail() {
  return <Report section={MAIN} />;
}

export function ExtendedModelDetail() {
  return <Report section={EXTENDED} />;
}
