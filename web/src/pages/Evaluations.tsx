import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type FailureItem } from "../api";
import { ErrorMsg, Loading, SensitiveTag } from "../components";
import { TRACK_BY_KEY } from "../constants";
import { wordDiff, type DiffPart } from "../diff";
import { useFilters } from "../filterContext";
import { useAsync } from "../hooks";

const TRACKS = ["simple", "topical", "phantom"] as const;
const OUTCOMES = [
  { key: "all", label: "All" },
  { key: "fail", label: "Failed" },
  { key: "pass", label: "Passed" },
] as const;

export function Evaluations() {
  const { runId = "" } = useParams();
  const { lang, version } = useFilters();
  const [params, setParams] = useSearchParams();
  const track = params.get("track") ?? "simple";
  const outcome = params.get("outcome") ?? "all";
  const [offset, setOffset] = useState(0);

  const { data, error, loading } = useAsync(
    () => api.evaluations(runId, track, outcome, lang, version, offset),
    [runId, track, outcome, lang, version, offset],
  );

  function update(next: Record<string, string | null>) {
    setOffset(0);
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v == null || v === "") p.delete(k);
      else p.set(k, v);
    }
    setParams(p);
  }

  const scope =
    (lang ? lang.toUpperCase() : "all languages") + (version ? " · one version" : "");

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={`/models/${encodeURIComponent(runId)}`}
          className="text-sm text-slate-400 hover:underline"
        >
          ← Back to model
        </Link>
        <h1 className="text-2xl font-bold mt-1">All evaluations</h1>
        <p className="text-slate-400 text-sm max-w-3xl">
          Every test's prompt, the model's full response, and the deterministic scoring — the
          scripture detected, the matching verse text, and the differences highlighted. Scoped by
          the header's language / version filter ({scope}).
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {TRACKS.map((t) => (
          <button
            key={t}
            onClick={() => update({ track: t })}
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

      <div className="flex flex-wrap gap-2 items-center">
        {OUTCOMES.map((o) => {
          const count =
            !data ? null : o.key === "all" ? data.n_pass + data.n_fail : o.key === "pass" ? data.n_pass : data.n_fail;
          return (
            <button
              key={o.key}
              onClick={() => update({ outcome: o.key })}
              className={`rounded-full px-3 py-1 text-xs ${
                outcome === o.key
                  ? "bg-white/15 text-white"
                  : "bg-white/5 text-slate-400 hover:bg-white/10"
              }`}
            >
              {o.label}
              {count != null ? ` (${count})` : ""}
            </button>
          );
        })}
      </div>

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && (
        <>
          <p className="text-sm text-slate-500">
            {data.total} shown · {data.n_pass} passed / {data.n_fail} failed for this filter
          </p>
          {data.items.length === 0 ? (
            <p className="text-slate-400 text-sm">No evaluations match this filter.</p>
          ) : (
            <div className="space-y-4">
              {data.items.map((it) => (
                <EvalCard key={it.id} item={it} track={track} />
              ))}
            </div>
          )}
          <Pager total={data.total} offset={offset} limit={data.limit} onPage={setOffset} />
        </>
      )}
    </div>
  );
}

function PassBadge({ passed, detail }: { passed?: boolean; detail?: string }) {
  return (
    <span
      className={`text-xs rounded px-2 py-0.5 whitespace-nowrap ${
        passed ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"
      }`}
    >
      {passed ? "Pass" : "Fail"}
      {detail ? ` · ${detail}` : ""}
    </span>
  );
}

function PromptBlock({ prompt }: { prompt?: string }) {
  if (!prompt) return null;
  return (
    <div className="rounded-lg bg-white/[0.03] border border-white/5 p-3">
      <div className="text-xs text-slate-500 mb-1">Prompt</div>
      <p className="text-sm text-slate-300 whitespace-pre-wrap">{prompt}</p>
    </div>
  );
}

function EvalCard({ item, track }: { item: FailureItem; track: string }) {
  if (track === "phantom") return <PhantomCard item={item} />;
  if (track === "topical") return <TopicalCard item={item} />;
  return <SimpleCard item={item} />;
}

function SimpleCard({ item }: { item: FailureItem }) {
  const { left, right } = wordDiff(item.expected_text ?? "", item.response_text ?? "");
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="font-mono text-sm">
          {item.reference} · {item.version_abbrev} ·{" "}
          <span className="text-slate-500">{item.language_tag}</span>
        </div>
        <PassBadge
          passed={item.passed}
          detail={`${item.grade} · QER ${item.qer?.toFixed(2)}`}
        />
      </div>
      <PromptBlock prompt={item.prompt} />
      <div className="grid md:grid-cols-2 gap-4 text-sm">
        <Side title="Expected (actual verse)" parts={left} />
        <Side title="Model response" parts={right} />
      </div>
    </div>
  );
}

function TopicalCard({ item }: { item: FailureItem }) {
  const quotes = item.quotes ?? [];
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm">
          <span className="font-medium">{item.topic_name}</span>
          <span className="text-slate-500">
            {" "}
            · {item.elicitation_level} · {item.language_tag}
          </span>
          {item.sensitive && <SensitiveTag />}
        </div>
        <PassBadge passed={item.passed} detail={`${((item.score ?? 0) * 100).toFixed(0)}`} />
      </div>
      <PromptBlock prompt={item.prompt} />
      {quotes.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-1">Scripture detected</div>
          <div className="space-y-1">
            {quotes.map((q, i) => (
              <div key={i} className="text-sm">
                <span className={`text-xs rounded px-1.5 py-0.5 mr-2 ${badgeClass(q.classification)}`}>
                  {q.classification}
                </span>
                <span className="font-serif">“{q.quote}”</span>
                {q.cited_usfm && <span className="text-slate-500"> — cited {q.cited_usfm}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      <details className="text-sm text-slate-400">
        <summary className="cursor-pointer">Full response</summary>
        <p className="mt-2 whitespace-pre-wrap">{item.response_text}</p>
      </details>
    </div>
  );
}

function PhantomCard({ item }: { item: FailureItem }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="font-mono text-sm">
          {item.reference} · {item.version_abbrev} ·{" "}
          <span className="text-slate-500">{item.language_tag}</span>
        </div>
        <PassBadge
          passed={item.passed}
          detail={
            item.passed
              ? "declined"
              : item.outcome === "quoted_real_verse"
                ? "substituted a real verse"
                : "invented a verse"
          }
        />
      </div>
      <div className="text-xs text-slate-500">
        This reference does not exist — the model should decline, not quote.
      </div>
      <PromptBlock prompt={item.prompt} />
      <div>
        <div className="text-xs text-slate-500 mb-1">Model response</div>
        <p className="text-sm whitespace-pre-wrap">{item.response_text || <em>(empty)</em>}</p>
      </div>
      {item.quotes && item.quotes.length > 0 && (
        <div className="space-y-1">
          {item.quotes.map((q, i) => (
            <div key={i} className="text-sm">
              <span className="text-xs rounded px-1.5 py-0.5 mr-2 bg-rose-500/15 text-rose-300">
                {q.classification}
              </span>
              <span className="font-serif">“{q.quote}”</span>
              {q.cited_usfm && <span className="text-slate-500"> — cited {q.cited_usfm}</span>}
            </div>
          ))}
        </div>
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
  if (c === "accurate") return "bg-emerald-500/15 text-emerald-300";
  if (c === "minor") return "bg-lime-500/15 text-lime-300";
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
  if (total <= limit) return null;
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
