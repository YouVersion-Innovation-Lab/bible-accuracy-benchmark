import { Link, useParams } from "react-router-dom";
import { api, type TrackSummary } from "../api";
import { Card, ErrorMsg, Loading, ScoreBadge } from "../components";
import { TRACKS, heatColor, langName, orderLanguages } from "../constants";
import { useAsync } from "../hooks";

export function ModelDetail() {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);

  if (loading) return <Loading />;
  if (error) return <ErrorMsg error={error} />;
  if (!data) return null;

  const s = data.summary;
  const simple = s.tracks.simple;
  const tracks = s.tracks;

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
          <div className="text-xs text-slate-400 uppercase tracking-wide">Bible Accuracy</div>
          <div className="text-3xl font-bold mt-1">
            <ScoreBadge score={s.headline_score} />
          </div>
          {s.headline_partial && (
            <div className="text-xs text-amber-400 mt-1">partial (not all tracks run)</div>
          )}
        </div>
      </div>

      <PlainLanguageCard label={data.model.label} simple={simple} tracks={tracks} />

      <div>
        <h2 className="text-lg font-semibold mb-3">What we measured</h2>
        <div className="grid sm:grid-cols-3 gap-4">
          {TRACKS.map((t) => {
            const ts = tracks[t.key];
            if (!ts) return null;
            return (
              <div key={t.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
                <div className="flex items-baseline justify-between">
                  <h3 className="font-semibold">{t.name}</h3>
                  <span className="text-2xl font-bold tabular-nums">
                    {(ts.track_score * 100).toFixed(1)}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1 mb-3 leading-relaxed">{t.blurb}</p>
                <TrackRates trackKey={t.key} ts={ts} />
              </div>
            );
          })}
        </div>
      </div>

      {simple?.by_language && Object.keys(simple.by_language).length > 0 && (
        <Card title="Direct-quote accuracy by language">
          <div className="flex flex-wrap gap-2">
            {orderLanguages(Object.keys(simple.by_language)).map((lang) => {
              const v = simple.by_language![lang];
              const { bg, fg } = heatColor(v);
              return (
                <div
                  key={lang}
                  className="rounded-lg px-3 py-2 text-sm min-w-24"
                  style={{ background: bg, color: fg }}
                >
                  <div className="text-xs opacity-80">{langName(lang)}</div>
                  <div className="font-semibold tabular-nums">{(v * 100).toFixed(0)}</div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <div className="flex flex-wrap gap-3">
        <Link
          to={`/models/${encodeURIComponent(runId)}/failures`}
          className="rounded-lg bg-indigo-500/20 text-indigo-200 px-4 py-2 text-sm hover:bg-indigo-500/30 no-underline"
        >
          Inspect every failure →
        </Link>
        <Link
          to="/methodology"
          className="rounded-lg bg-white/5 text-slate-200 px-4 py-2 text-sm hover:bg-white/10 no-underline"
        >
          How scoring works
        </Link>
      </div>
    </div>
  );
}

/** Plain-language summary for non-technical readers (pastors, Christian devs). */
function PlainLanguageCard({
  label,
  simple,
  tracks,
}: {
  label: string;
  simple?: TrackSummary;
  tracks: Record<string, TrackSummary>;
}) {
  if (!simple) return null;
  const langs = simple.by_language ?? {};
  const entries = Object.entries(langs);
  const best = entries.slice().sort((a, b) => b[1] - a[1]).slice(0, 2).map(([l]) => langName(l));
  const worst = entries.slice().sort((a, b) => a[1] - b[1]).slice(0, 1).map(([l]) => langName(l));
  const near = (simple.near_verbatim_rate ?? 0) * 100;
  const fab = (simple.fabrication_rate ?? 0) * 100;
  const adv = tracks.adversarial?.track_score;

  return (
    <div className="rounded-xl border border-indigo-400/20 bg-indigo-400/[0.06] p-5">
      <h2 className="text-sm font-semibold text-indigo-200 mb-2">What this means for you</h2>
      <p className="leading-relaxed text-slate-200">
        When asked to quote a specific verse, <strong>{label}</strong> gets it word-for-word (or
        nearly so) <strong>{near.toFixed(0)}%</strong> of the time
        {best.length ? (
          <> — most reliably in {best.join(" and ")}{worst.length ? `, least in ${worst[0]}` : ""}</>
        ) : null}
        . It stated something as scripture that matches no real Bible text{" "}
        <strong>{fab.toFixed(0)}%</strong> of the time
        {adv != null ? (
          <>
            , and it resisted deliberate attempts to make it misquote{" "}
            <strong>{(adv * 100).toFixed(0)}%</strong> of the time
          </>
        ) : null}
        .
      </p>
      <p className="text-xs text-slate-400 mt-2">
        Higher is better. This reflects quotation accuracy only — not the model's theology.
      </p>
    </div>
  );
}

function TrackRates({ trackKey, ts }: { trackKey: string; ts: TrackSummary }) {
  const rows: [string, string][] = [];
  if (trackKey === "simple") {
    rows.push(["Word-perfect", pct(ts.verbatim_rate)]);
    rows.push(["Fabricated a verse", pct(ts.fabrication_rate)]);
    rows.push(["Declined to answer", pct(ts.refusal_rate)]);
    rows.push(["Wrong translation", pct(ts.wrong_version_rate)]);
  } else if (trackKey === "topical") {
    if (ts.sensitive_topic_score != null)
      rows.push(["On sensitive topics", (ts.sensitive_topic_score * 100).toFixed(0)]);
    Object.entries(ts.emission_rate_by_level ?? {}).forEach(([lvl, v]) =>
      rows.push([`Quoted when asked (${lvl})`, pct(v)]),
    );
  } else if (trackKey === "adversarial") {
    rows.push(["Held firm on 1st attempt", pct(ts.resistance_at_1)]);
    rows.push(["Corrected the user", pct(ts.correction_rate)]);
  }
  return (
    <div className="space-y-0.5">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between text-sm">
          <span className="text-slate-400">{k}</span>
          <span className="tabular-nums">{v}</span>
        </div>
      ))}
    </div>
  );
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}
