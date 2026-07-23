import { Link, useParams } from "react-router-dom";
import { api, type TrackSummary } from "../api";
import { Loading, ScoreBadge } from "../components";
import { TRACK_WEIGHTS, TRACKS } from "../constants";
import { sliceLabel } from "../FilterBar";
import { useFilters } from "../filterContext";
import { useAsync } from "../hooks";

export function ModelDetail() {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);
  // Language + Bible version come from the global (header) filter.
  const { lang, version, versionsByLang } = useFilters();

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

  const abbrev =
    version != null
      ? versionsByLang.get(lang ?? "")?.find((v) => v.version_id === version)?.version_abbrev
      : undefined;
  const filtered = lang != null;
  const sliceText = filtered ? sliceLabel(lang, abbrev) : "all languages";

  // Each track's score (0..1) for the active slice.
  const trackScore = (key: string) => trackSlice(tracks[key], lang, version);

  // Header Overall Score: the headline (across all languages) when unfiltered,
  // else the same weighted blend restricted to the slice and renormalized over
  // the tracks that cover it.
  const overall: number | null = (() => {
    if (!filtered) return s.headline_score ?? null;
    let num = 0;
    let den = 0;
    for (const t of TRACKS) {
      const v = trackScore(t.key);
      const w = TRACK_WEIGHTS[t.key] ?? 0;
      if (v != null) {
        num += w * v;
        den += w;
      }
    }
    return den > 0 ? (num / den) * 100 : null;
  })();

  const evalHref = (trackKey: string) =>
    `/models/${encodeURIComponent(runId)}/evaluations?track=${trackKey}`;

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
            <ScoreBadge score={overall} />
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {filtered ? sliceText : "50% single-verse · 25% topical · 25% hallucination"}
          </div>
          {s.headline_partial && !filtered && (
            <div className="text-xs text-amber-400 mt-1">partial (not all tracks run)</div>
          )}
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-1">What we measured</h2>
        <p className="text-xs text-slate-500 mb-3">
          Scores shown for <span className="text-slate-300">{sliceText}</span> — change the
          language / version in the header filter.
        </p>
        <div className="grid sm:grid-cols-3 gap-4">
          {TRACKS.map((t) => {
            const ts = tracks[t.key];
            if (!ts) return null;
            const score = trackScore(t.key);
            return (
              <div key={t.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="font-semibold">{t.name}</h3>
                  <span className="text-2xl font-bold tabular-nums">
                    {score != null ? (score * 100).toFixed(1) : "—"}
                  </span>
                </div>
                <div className="text-xs text-slate-500">{sliceText}</div>
                <p className="text-xs text-slate-400 mt-2 mb-3 leading-relaxed">{t.blurb}</p>
                <Link to={evalHref(t.key)} className="text-xs text-indigo-300 hover:underline">
                  Browse evaluations →
                </Link>
              </div>
            );
          })}
        </div>
      </div>

      <Link to="/methodology" className="inline-block text-sm text-slate-400 hover:underline">
        How scoring works →
      </Link>
    </div>
  );
}

// Score (0..1) for a track at the active slice: a specific version, else a
// language, else the track's overall.
function trackSlice(
  ts: TrackSummary | undefined,
  lang: string | null,
  version: number | null,
): number | undefined {
  if (!ts) return undefined;
  if (version != null) return ts.versions?.find((v) => v.version_id === version)?.score;
  if (lang) return ts.by_language?.[lang];
  return ts.track_score;
}
