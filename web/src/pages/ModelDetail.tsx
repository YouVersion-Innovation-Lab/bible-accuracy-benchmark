import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Card, ErrorMsg, Loading, Pct, ScoreBadge } from "../components";
import { useAsync } from "../hooks";

export function ModelDetail() {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);

  if (loading) return <Loading />;
  if (error) return <ErrorMsg error={error} />;
  if (!data) return null;

  const s = data.summary;
  const simple = s.tracks.simple;
  const topical = s.tracks.topical;
  const adv = s.tracks.adversarial;

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <Link to="/" className="text-sm text-slate-400 hover:underline">
            ← Leaderboard
          </Link>
          <h1 className="text-3xl font-bold mt-1">{data.model.label}</h1>
          <p className="text-slate-500 text-sm">{data.model.base_url_host}</p>
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

      <div className="grid sm:grid-cols-3 gap-4">
        {simple && (
          <Card title="Simple track">
            <Metric label="Score" value={`${(simple.track_score * 100).toFixed(1)}`} />
            <Row label="Verbatim rate"><Pct v={simple.verbatim_rate} /></Row>
            <Row label="Fabrication rate"><Pct v={simple.fabrication_rate} /></Row>
            <Row label="Refusal rate"><Pct v={simple.refusal_rate} /></Row>
            <Row label="Wrong-version rate"><Pct v={simple.wrong_version_rate} /></Row>
          </Card>
        )}
        {topical && (
          <Card title="Topical track">
            <Metric label="Score" value={`${(topical.track_score * 100).toFixed(1)}`} />
            <Row label="Sensitive-topic score">
              {topical.sensitive_topic_score != null
                ? (topical.sensitive_topic_score * 100).toFixed(1)
                : "—"}
            </Row>
            {topical.emission_rate_by_level &&
              Object.entries(topical.emission_rate_by_level).map(([lvl, v]) => (
                <Row key={lvl} label={`Emission ${lvl}`}><Pct v={v} /></Row>
              ))}
          </Card>
        )}
        {adv && (
          <Card title="Adversarial track">
            <Metric label="Resistance@3" value={`${(adv.track_score * 100).toFixed(1)}`} />
            <Row label="Resistance@1"><Pct v={adv.resistance_at_1} /></Row>
            <Row label="Correction rate"><Pct v={adv.correction_rate} /></Row>
          </Card>
        )}
      </div>

      {simple?.by_language && (
        <Card title="Simple track by language">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-1 text-sm">
            {Object.entries(simple.by_language)
              .sort((a, b) => a[1] - b[1])
              .map(([lang, v]) => (
                <Row key={lang} label={lang}>{(v * 100).toFixed(1)}</Row>
              ))}
          </div>
        </Card>
      )}

      <div className="flex gap-3">
        <Link
          to={`/models/${encodeURIComponent(runId)}/failures`}
          className="rounded-lg bg-indigo-500/20 text-indigo-200 px-4 py-2 text-sm hover:bg-indigo-500/30 no-underline"
        >
          Browse failures →
        </Link>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between py-0.5 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="tabular-nums">{children}</span>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-2">
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
