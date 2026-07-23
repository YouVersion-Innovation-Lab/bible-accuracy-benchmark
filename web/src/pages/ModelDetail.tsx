import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TrackSummary } from "../api";
import { Card, ErrorMsg, Loading, ScoreBadge } from "../components";
import { TRACKS, heatColor, langName } from "../constants";
import { sliceLabel } from "../FilterBar";
import { useFilters } from "../filterContext";
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
          <div className="text-xs text-slate-400 uppercase tracking-wide">Overall Score</div>
          <div className="text-3xl font-bold mt-1">
            <ScoreBadge score={s.headline_score} />
          </div>
          <div className="text-xs text-slate-500 mt-1">
            50% single-verse · 25% topical · 25% hallucination
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
        <AccuracyExplorer runId={runId} tracks={tracks} />
      )}

      <div className="flex flex-wrap gap-3">
        <Link
          to={`/models/${encodeURIComponent(runId)}/evaluations`}
          className="rounded-lg bg-indigo-500/20 text-indigo-200 px-4 py-2 text-sm hover:bg-indigo-500/30 no-underline"
        >
          Browse all evaluations →
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

/** This model's score on every track for the globally-selected language and
 * Bible version, its spontaneous translation preference, and deep links into
 * the evaluations browser. The language/version selector is in the header and
 * applies site-wide. */
function AccuracyExplorer({
  runId,
  tracks,
}: {
  runId: string;
  tracks: Record<string, TrackSummary>;
}) {
  const { lang, version, versionsByLang } = useFilters();
  const abbrev =
    version != null
      ? versionsByLang.get(lang ?? "")?.find((v) => v.version_id === version)?.version_abbrev
      : undefined;
  const label = sliceLabel(lang, abbrev);

  const abbrevById = useMemo(() => {
    const m = new Map<number, string>();
    (tracks.simple?.versions ?? []).forEach((v) => m.set(v.version_id, v.version_abbrev));
    return m;
  }, [tracks.simple]);

  // Per-track score (0..1) for the active slice.
  const rows = TRACKS.map((t) => ({ meta: t, score: trackSlice(tracks[t.key], lang, version) }));

  // Spontaneous translation preference (topical L2) for the selected language.
  const pref = tracks.topical?.version_preference ?? {};
  const prefLang = lang && pref[lang] ? lang : null;
  const prefEntry = prefLang ? pref[prefLang] : null;
  const prefAbbrev = prefEntry
    ? (abbrevById.get(prefEntry.top_version_id) ?? `#${prefEntry.top_version_id}`)
    : null;

  // The evaluations browser reads the same global filter, so only the track
  // needs to travel in the URL.
  const evalHref = (trackKey: string) =>
    `/models/${encodeURIComponent(runId)}/evaluations?track=${trackKey}`;

  return (
    <Card title="Accuracy by language & version">
      <div className="text-sm text-slate-400">
        Scores for <span className="text-slate-200">{label}</span>
        <span className="text-slate-500"> — set the language / version in the header filter.</span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {rows.map((r) => {
          const { bg, fg } = heatColor(r.score);
          return (
            <div key={r.meta.key} className="rounded-xl border border-white/10 p-4">
              <div className="text-xs text-slate-400">{r.meta.name}</div>
              <div
                className="mt-1 inline-block rounded px-2 py-0.5 text-2xl font-bold tabular-nums"
                style={{ background: bg, color: fg }}
              >
                {r.score != null ? (r.score * 100).toFixed(1) : "—"}
              </div>
              <div className="mt-2">
                <Link to={evalHref(r.meta.key)} className="text-xs text-indigo-300 hover:underline">
                  Browse evaluations →
                </Link>
              </div>
            </div>
          );
        })}
      </div>
      {prefEntry && prefAbbrev ? (
        <p className="mt-4 text-sm text-slate-300">
          When not told which translation to use, it most often quoted{" "}
          <strong>{prefAbbrev}</strong> in {langName(prefLang!)} (
          {prefEntry.by_version[String(prefEntry.top_version_id)]}/{prefEntry.n} quotes).
        </p>
      ) : lang ? (
        <p className="mt-4 text-sm text-slate-500">
          No spontaneous-preference data for {langName(lang)} (only one translation offered).
        </p>
      ) : (
        <p className="mt-4 text-sm text-slate-500">
          Pick a language in the header filter to scope every track and see which translation
          this model prefers when unprompted.
        </p>
      )}
    </Card>
  );
}

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
  const phantom = tracks.phantom?.track_score;

  return (
    <div className="rounded-xl border border-indigo-400/20 bg-indigo-400/[0.06] p-5">
      <h2 className="text-sm font-semibold text-indigo-200 mb-2">What this means for you</h2>
      <p className="leading-relaxed text-slate-200">
        Asked to quote one specific verse in a named translation, <strong>{label}</strong> returns it
        word-for-word (or within a character or two) <strong>{near.toFixed(0)}%</strong> of the time
        {best.length ? (
          <> — most reliably in {best.join(" and ")}{worst.length ? `, least in ${worst[0]}` : ""}</>
        ) : null}
        . It presented text as scripture that matches no real Bible verse{" "}
        <strong>{fab.toFixed(0)}%</strong> of the time
        {phantom != null ? (
          <>
            , and when asked for a verse that doesn't exist it correctly declined to quote{" "}
            <strong>{(phantom * 100).toFixed(0)}%</strong> of the time
          </>
        ) : null}
        .
      </p>
      <p className="text-xs text-slate-400 mt-2">
        Higher is better. These numbers measure only the accuracy of scripture the model quotes —
        not the theology of its answers.
      </p>
    </div>
  );
}

function TrackRates({ trackKey, ts }: { trackKey: string; ts: TrackSummary }) {
  const rows: [string, string][] = [];
  if (trackKey === "simple") {
    rows.push(["Character-exact match", pct(ts.verbatim_rate)]);
    rows.push(["Invented a verse", pct(ts.fabrication_rate)]);
    rows.push(["Declined to quote", pct(ts.refusal_rate)]);
    rows.push(["Quoted the wrong translation", pct(ts.wrong_version_rate)]);
  } else if (trackKey === "topical") {
    if (ts.sensitive_topic_score != null)
      rows.push(["Score on sensitive topics", (ts.sensitive_topic_score * 100).toFixed(0)]);
    Object.entries(ts.emission_rate_by_level ?? {}).forEach(([lvl, v]) =>
      rows.push([`Quoted a verse (${lvl})`, pct(v)]),
    );
  } else if (trackKey === "phantom") {
    rows.push(["Correctly declined", pct(ts.refusal_rate)]);
    rows.push(["Invented / substituted a verse", pct(ts.hallucination_rate)]);
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
