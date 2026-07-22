import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type FailureItem } from "../api";
import { ErrorMsg, Loading, SensitiveTag } from "../components";
import { TRACK_BY_KEY, orderLanguages } from "../constants";
import { FilterBar, buildVersionsByLang } from "../FilterBar";
import { wordDiff, type DiffPart } from "../diff";
import { useAsync } from "../hooks";

const TRACKS = ["simple", "topical", "adversarial"] as const;

export function Failures() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const track = params.get("track") ?? "simple";
  const language = params.get("language");
  const versionId = params.get("version_id") ? Number(params.get("version_id")) : null;
  const [offset, setOffset] = useState(0);

  // Run detail supplies the language/version options for the filter.
  const { data: run } = useAsync(() => api.run(runId), [runId]);
  const simple = run?.summary.tracks.simple;
  const versionsByLang = useMemo(() => buildVersionsByLang(simple?.versions ?? []), [simple]);
  const languages = useMemo(
    () => orderLanguages(Object.keys(simple?.by_language ?? {})),
    [simple],
  );

  const { data, error, loading } = useAsync(
    () => api.failures(runId, track, language, offset, versionId),
    [runId, track, language, versionId, offset],
  );

  // Merge changes into the URL query (single source of truth) and reset paging.
  function update(next: Record<string, string | null>) {
    setOffset(0);
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v == null || v === "") p.delete(k);
      else p.set(k, v);
    }
    setParams(p);
  }
  const setTrack = (t: string) => update({ track: t });

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/models/${encodeURIComponent(runId)}`} className="text-sm text-slate-400 hover:underline">
          ← Back to model
        </Link>
        <h1 className="text-2xl font-bold mt-1">Failure browser</h1>
        <p className="text-slate-400 text-sm">
          Where the model presented scripture inaccurately. Expected text is the actual
          verse in the cited translation.
        </p>
      </div>

      <div className="flex gap-2">
        {TRACKS.map((t) => (
          <button
            key={t}
            onClick={() => setTrack(t)}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              track === t
                ? "bg-indigo-500/30 text-indigo-100"
                : "bg-white/5 text-slate-300 hover:bg-white/10"
            }`}
          >
            {TRACK_BY_KEY[t]?.name ?? t}
          </button>
        ))}
      </div>

      {languages.length > 0 && (
        <FilterBar
          languages={languages}
          versionsByLang={versionsByLang}
          lang={language}
          version={versionId}
          onLang={(l) => update({ language: l, version_id: null })}
          onVersion={(v) => update({ version_id: v == null ? null : String(v) })}
          versionEnabled={track === "simple"}
        />
      )}

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && (
        <>
          <p className="text-sm text-slate-500">{data.total} failing items</p>
          <div className="space-y-4">
            {data.items.map((it) => (
              <FailureCard key={it.id} item={it} track={track} />
            ))}
          </div>
          <Pager
            total={data.total}
            offset={offset}
            limit={data.limit}
            onPage={setOffset}
          />
        </>
      )}
    </div>
  );
}

function FailureCard({ item, track }: { item: FailureItem; track: string }) {
  if (track === "adversarial") return <AdversarialCard item={item} />;
  if (track === "topical") return <TopicalCard item={item} />;
  return <SimpleCard item={item} />;
}

function SimpleCard({ item }: { item: FailureItem }) {
  const { left, right } = wordDiff(item.expected_text ?? "", item.response_text ?? "");
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="font-mono text-sm">
          {item.reference} · {item.version_abbrev} · <span className="text-slate-500">{item.language_tag}</span>
        </div>
        <span className="text-xs rounded bg-rose-500/15 text-rose-300 px-2 py-0.5">
          {item.grade} · QER {item.qer?.toFixed(2)}
        </span>
      </div>
      <div className="grid md:grid-cols-2 gap-4 text-sm">
        <Side title="Expected (actual verse)" parts={left} />
        <Side title="Model response" parts={right} />
      </div>
    </div>
  );
}

function TopicalCard({ item }: { item: FailureItem }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-2">
        <span className="font-medium">{item.topic_name}</span>
        <span className="text-slate-500 text-sm"> · {item.elicitation_level} · {item.language_tag}</span>
        {item.sensitive && <SensitiveTag />}
      </div>
      <div className="space-y-1 mb-3">
        {(item.quotes ?? [])
          .filter((q) => q.classification !== "accurate")
          .map((q, i) => (
            <div key={i} className="text-sm">
              <span className={`text-xs rounded px-1.5 py-0.5 mr-2 ${badgeClass(q.classification)}`}>
                {q.classification}
              </span>
              <span className="font-serif">“{q.quote}”</span>
              {q.cited_usfm && <span className="text-slate-500"> — cited {q.cited_usfm}</span>}
            </div>
          ))}
      </div>
      <details className="text-sm text-slate-400">
        <summary className="cursor-pointer">Full response</summary>
        <p className="mt-2 whitespace-pre-wrap">{item.response_text}</p>
      </details>
    </div>
  );
}

function AdversarialCard({ item }: { item: FailureItem }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-2 text-sm">
        <span className="text-xs rounded bg-rose-500/15 text-rose-300 px-2 py-0.5 mr-2">
          {item.category}
        </span>
        {item.target_usfm && <span className="font-mono">{item.target_usfm}</span>}
      </div>
      {item.attacker && (
        <p className="text-sm text-slate-300 mb-2">
          <span className="text-slate-500">Attacker:</span> {item.attacker}
        </p>
      )}
      <p className="text-sm whitespace-pre-wrap">
        <span className="text-slate-500">Model:</span> {item.response_text}
      </p>
      {item.reasons && item.reasons.length > 0 && (
        <p className="mt-2 text-xs text-rose-300">{item.reasons.join("; ")}</p>
      )}
    </div>
  );
}

function Side({ title, parts }: { title: string; parts: DiffPart[] }) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{title}</div>
      <p className="leading-relaxed font-serif">
        {parts.map((p, i) => (
          <span
            key={i}
            className={
              p.kind === "del"
                ? "bg-rose-500/25 rounded"
                : p.kind === "add"
                  ? "bg-emerald-500/25 rounded"
                  : ""
            }
          >
            {p.text}
          </span>
        ))}
      </p>
    </div>
  );
}

function badgeClass(c: string): string {
  if (c === "fabricated" || c === "fabricated_ref") return "bg-rose-500/15 text-rose-300";
  if (c === "misattributed") return "bg-amber-500/15 text-amber-300";
  return "bg-orange-500/15 text-orange-300";
}

function Pager({
  total,
  offset,
  limit,
  onPage,
}: {
  total: number;
  offset: number;
  limit: number;
  onPage: (n: number) => void;
}) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <button
        disabled={offset === 0}
        onClick={() => onPage(Math.max(0, offset - limit))}
        className="rounded px-3 py-1 bg-white/5 disabled:opacity-30 hover:bg-white/10"
      >
        Prev
      </button>
      <span className="text-slate-500">
        {Math.min(offset + 1, total)}–{Math.min(offset + limit, total)} of {total}
      </span>
      <button
        disabled={offset + limit >= total}
        onClick={() => onPage(offset + limit)}
        className="rounded px-3 py-1 bg-white/5 disabled:opacity-30 hover:bg-white/10"
      >
        Next
      </button>
    </div>
  );
}
