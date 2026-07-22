import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TrackSummary } from "../api";
import { Card, ErrorMsg, Loading, ScoreBadge } from "../components";
import { TRACKS, heatColor, langName, orderLanguages } from "../constants";
import { FilterBar, buildVersionsByLang, sliceLabel } from "../FilterBar";
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
        <DirectQuoteSection runId={runId} simple={simple} />
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

/** Filterable direct-quotation drill-down: pick a language and Bible version to
 * scope this model's accuracy score, its breakdown, and the failure browser. */
function DirectQuoteSection({ runId, simple }: { runId: string; simple: TrackSummary }) {
  const [lang, setLang] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);

  const versionsByLang = useMemo(
    () => buildVersionsByLang(simple.versions ?? []),
    [simple.versions],
  );
  const languages = useMemo(
    () => orderLanguages(Object.keys(simple.by_language ?? {})),
    [simple.by_language],
  );

  const langVersions = lang ? (versionsByLang.get(lang) ?? []) : [];
  const abbrev =
    version != null
      ? langVersions.find((v) => v.version_id === version)?.version_abbrev
      : undefined;

  // This model's accuracy (0..1) for the active slice.
  const score =
    version != null
      ? simple.versions?.find((v) => v.version_id === version)?.score
      : lang
        ? simple.by_language?.[lang]
        : simple.track_score;

  // Chips beneath the headline number: languages (all), a language's versions
  // (language selected), or the single chosen version.
  const chips: { key: string; label: string; value: number | undefined }[] = (() => {
    if (version != null) {
      const v = langVersions.find((x) => x.version_id === version);
      return v ? [{ key: `v${v.version_id}`, label: v.version_abbrev, value: v.score }] : [];
    }
    if (lang) {
      if (langVersions.length > 1) {
        return [
          { key: "overall", label: `${langName(lang)} overall`, value: simple.by_language?.[lang] },
          ...langVersions.map((v) => ({
            key: `v${v.version_id}`,
            label: v.version_abbrev,
            value: v.score,
          })),
        ];
      }
      return [{ key: "overall", label: langName(lang), value: simple.by_language?.[lang] }];
    }
    return languages.map((l) => ({ key: l, label: langName(l), value: simple.by_language?.[l] }));
  })();

  const failuresHref = (() => {
    const p = new URLSearchParams({ track: "simple" });
    if (lang) p.set("language", lang);
    if (version != null) p.set("version_id", String(version));
    return `/models/${encodeURIComponent(runId)}/failures?${p}`;
  })();

  const label = sliceLabel(lang, abbrev);

  return (
    <Card title="Direct-quote accuracy">
      <FilterBar
        languages={languages}
        versionsByLang={versionsByLang}
        lang={lang}
        version={version}
        onLang={(l) => {
          setLang(l);
          setVersion(null);
        }}
        onVersion={setVersion}
      />
      <div className="mt-5 flex items-baseline gap-3">
        <div className="text-4xl font-bold tabular-nums">
          {score != null ? (score * 100).toFixed(1) : "—"}
        </div>
        <div className="text-sm text-slate-400">accuracy · {label}</div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {chips.map((c) => {
          const { bg, fg } = heatColor(c.value);
          return (
            <div
              key={c.key}
              className="rounded-lg px-3 py-2 text-sm min-w-24"
              style={{ background: bg, color: fg }}
            >
              <div className="text-xs opacity-80">{c.label}</div>
              <div className="font-semibold tabular-nums">
                {c.value == null ? "—" : (c.value * 100).toFixed(0)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-4">
        <Link to={failuresHref} className="text-sm text-indigo-300 hover:underline">
          Inspect {label === "overall" ? "" : `${label} `}failures →
        </Link>
      </div>
    </Card>
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
