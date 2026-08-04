/**
 * One page per (model, dimension): every test case for that dimension, each
 * showing how its score was derived. Reached from the dimension cards on the
 * model page — there is deliberately no dimension switcher here, because the
 * three dimensions are scored by different rules and read best on their own
 * terms.
 */
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorMsg, Loading } from "../components";
import { TRACK_BY_KEY, langName } from "../constants";
import { HallucinationWork, SimpleWork } from "../evalWork";
import { useAsync } from "../hooks";
import { modelHref, sectionForTrack } from "../sections";

const OUTCOMES = [
  { key: "all", label: "All" },
  { key: "fail", label: "Failed" },
  { key: "pass", label: "Passed" },
] as const;

/** What each dimension asks of the model, and how a case passes. */
const INTRO: Record<string, string> = {
  simple:
    "Each test names one verse and one translation and asks for that verse only. The response is " +
    "compared character-by-character against the real verse; a case passes when the wording is " +
    "accurate enough to be a faithful quotation.",
  hallucination:
    "Each test names a translation and asks it for a reference that translation does not " +
    "contain — so these prompts are word-for-word the Direct Quotation prompts, differing only " +
    "in that the reference isn't there. A case passes " +
    "when the model declines rather than producing scripture — ideally saying why the reference " +
    "isn't in the Bible.",
};

export function TrackEvaluations() {
  const { runId = "", track = "simple" } = useParams();
  const [params, setParams] = useSearchParams();
  const outcome = params.get("outcome") ?? "all";
  // The subset being read lives in the URL — arrived at by clicking a cell on
  // the model page — so a drilled-down view is shareable and reversible.
  const lang = params.get("language");
  const versionParam = params.get("version_id");
  const version = versionParam ? Number(versionParam) : null;
  const [offset, setOffset] = useState(0);

  const meta = TRACK_BY_KEY[track];

  // A different subset re-queries from the top; keeping a deep offset across a
  // narrower result set would land on an empty page.
  useEffect(() => setOffset(0), [track, outcome, lang, version]);

  const run = useAsync(() => api.run(runId), [runId]);
  const { data, error, loading } = useAsync(
    () => api.evaluations(runId, track, outcome, lang, version, offset),
    [runId, track, outcome, lang, version, offset],
  );

  const label = run.data?.model.label ?? runId;
  const abbrev =
    version == null
      ? null
      : (run.data?.summary.tracks[track]?.versions?.find((v) => v.version_id === version)
          ?.version_abbrev ?? `#${version}`);
  const scope = [lang ? langName(lang) : "all languages", abbrev].filter(Boolean).join(" · ");
  // Keep the outcome tab when widening the subset back out to the whole run.
  const wholeRun = outcome === "all" ? "" : `?outcome=${outcome}`;
  // Both boards share this page, so "back" has to return to whichever one owns
  // this dimension — landing on the scored board after drilling in from the beta
  // board would quietly suggest the number you just read was part of the ranking.
  const section = sectionForTrack(track);
  const backToModel = modelHref(section, runId);

  if (!meta) {
    return (
      <div className="space-y-3">
        <p className="text-slate-300">Unknown evaluation dimension “{track}”.</p>
        <Link to={backToModel} className="text-indigo-300 hover:underline">
          ← Back to model
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to={backToModel} className="text-sm text-slate-400 hover:underline">
          ← Back to {label}
        </Link>
        <h1 className="text-2xl font-bold mt-1">
          {label} <span className="text-slate-500">·</span> {meta.name}
          {section.beta && (
            <span className="ml-2 rounded bg-amber-400/15 text-amber-300 text-[10px] uppercase tracking-wide px-1.5 py-0.5 align-middle">
              extended · beta
            </span>
          )}
        </h1>
        <p className="text-slate-400 text-sm mt-1 leading-normal">{INTRO[track]}</p>
        <p className="text-slate-500 text-xs mt-2">
          Showing <span className="text-slate-300">{scope}</span>. Every case below lists its own
          score and the steps that produced it; nothing is recomputed in the browser.
          {(lang || version != null) && (
            <>
              {" "}
              <Link
                to={`/models/${encodeURIComponent(runId)}/evaluations/${track}${wholeRun}`}
                className="text-indigo-300 hover:underline"
              >
                Show every language →
              </Link>
            </>
          )}
        </p>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        {OUTCOMES.map((o) => {
          const count = !data
            ? null
            : o.key === "all"
              ? data.n_pass + data.n_fail
              : o.key === "pass"
                ? data.n_pass
                : data.n_fail;
          return (
            <button
              key={o.key}
              onClick={() => {
                const p = new URLSearchParams(params);
                if (o.key === "all") p.delete("outcome");
                else p.set("outcome", o.key);
                setParams(p);
              }}
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
            {data.total} test case{data.total === 1 ? "" : "s"} in this view
            {data.total > data.limit && (
              <>
                {" "}
                · showing {offset + 1}–{Math.min(offset + data.limit, data.total)}
              </>
            )}
            {outcome === "all" && ` · ${data.n_pass} passed / ${data.n_fail} failed`}
          </p>
          {data.items.length === 0 ? (
            <p className="text-slate-400 text-sm">No test cases in this view.</p>
          ) : (
            <div className="space-y-4">
              {data.items.map((it) =>
                track === "hallucination" ? (
                  <HallucinationWork key={it.id} item={it} />
                ) : (
                  <SimpleWork key={it.id} item={it} />
                ),
              )}
            </div>
          )}
          <Pager total={data.total} offset={offset} limit={data.limit} onPage={setOffset} />
        </>
      )}
    </div>
  );
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
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="flex items-center gap-3 text-sm">
      <button
        disabled={offset === 0}
        onClick={() => onPage(Math.max(0, offset - limit))}
        className="rounded-lg bg-white/5 px-3 py-1.5 disabled:opacity-40 hover:bg-white/10"
      >
        Prev
      </button>
      <span className="text-slate-500">
        Page {page} of {pages}
      </span>
      <button
        disabled={offset + limit >= total}
        onClick={() => onPage(offset + limit)}
        className="rounded-lg bg-white/5 px-3 py-1.5 disabled:opacity-40 hover:bg-white/10"
      >
        Next
      </button>
    </div>
  );
}
