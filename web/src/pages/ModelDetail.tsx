import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type SummarySlice, type SummaryView, type TrackSummary } from "../api";
import { BetaNotice, HeatCell, Loading, ScoreBadge } from "../components";
import { langName, orderLanguages } from "../constants";
import { DimensionBreakdown } from "../dimensionDetail";
import { useAsync } from "../hooks";
import {
  EXTENDED,
  MAIN,
  blendForSlice,
  modelHref,
  sectionTracks,
  versionColumnsInform,
  type Section,
} from "../sections";
import { ScoreFactors } from "../scoreFactors";
import { evalHref, languageSlices, sliceScore, versionSlices, type Slice } from "../slices";

export function Report({ section }: { section: Section }) {
  const { runId = "" } = useParams();
  const { data, error, loading } = useAsync(() => api.run(runId), [runId]);
  // Which translation the whole page is narrowed to. Every panel below reads
  // from the matching slice, so one piece of state moves the entire report.
  const [versionId, setVersionId] = useState<number | null>(null);

  const s = data?.summary;
  const options = useMemo(() => translationOptions(section, s?.slices ?? []), [section, s]);
  const slice = versionId == null ? null : (options.find((o) => o.version_id === versionId) ?? null);
  // The slice and the run summary are the same shape on purpose: swapping which
  // one the page reads is the whole filter mechanism.
  const view: SummaryView | undefined = slice ?? s;

  if (loading) return <Loading />;
  if (error || !s || !view)
    return (
      <div className="space-y-3">
        <Link to={section.base || "/"} className="text-sm text-slate-400 hover:underline">
          ← {section.nav}
        </Link>
        <p className="text-slate-300">
          This model's results aren't available right now — the run may have been re-run or
          unpublished since the leaderboard was built. Head back to the leaderboard for the
          current results.
        </p>
      </div>
    );
  if (!data) return null;

  const tracks = view.tracks;
  const present = sectionTracks(section, (k) => tracks[k]);

  if (present.length === 0)
    return (
      <div className="space-y-3">
        <Link to={section.base || "/"} className="text-sm text-slate-400 hover:underline">
          ← {section.nav}
        </Link>
        <p className="text-slate-300">
          This run has no {section.beta ? "Extended Benchmark" : "scored"} results — it was
          evaluated without {section.tracks.map((t) => t.name).join(" or ")}.
        </p>
      </div>
    );

  const trackList = present.map((p) => p.ts);
  const langCols = languageSlices(trackList);
  const allVerCols = versionSlices(trackList);
  const verCols = versionColumnsInform(langCols.length, allVerCols.length) ? allVerCols : [];
  const scoreAt = (sl: Slice) => (k: string) => sliceScore(tracks[k], sl);

  // Drill-down for a dimension under the active filter. A translation-scoped
  // dimension narrows to the translation; one that names no translation narrows
  // to its language — asking for KJV's Hallucination items would return none,
  // because those prompts were built from the NIV.
  const evalFor = (trackKey: string) =>
    slice
      ? evalHref(runId, trackKey, {
          key: `ver:${slice.version_id}`,
          lang: slice.language_tag,
          versionId: slice.translation_scoped.includes(trackKey) ? slice.version_id : null,
          label: slice.version_abbrev,
        })
      : evalHref(runId, trackKey);

  const scopeText = slice
    ? `${slice.version_abbrev} · ${langName(slice.language_tag)}`
    : "every language and translation";

  return (
    <div className="space-y-8">
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
          <div className="text-xs text-slate-400 uppercase tracking-wide">
            {section.beta ? "Extended Score" : "Overall Score"}
          </div>
          <div className="text-3xl font-bold mt-1">
            <ScoreBadge score={section.summaryScoreOf(view)} />
          </div>
          <div className="text-xs text-slate-500 mt-1">{section.composition}</div>
          <div className="text-xs text-slate-500">{scopeText}</div>
          {s.headline_partial && !section.beta && (
            <div className="text-xs text-amber-400 mt-1">partial (not all dimensions run)</div>
          )}
        </div>
      </div>

      {options.length > 1 && (
        <TranslationFilter
          options={options}
          value={versionId}
          onChange={setVersionId}
          slice={slice}
          section={section}
        />
      )}

      {section.beta && <BetaNotice />}

      <ScoreFactors factors={section.factorsOf(view)} score={section.summaryScoreOf(view)} />

      <div>
        <h2 className="text-lg font-semibold mb-1">What we measured</h2>
        <p className="text-xs text-slate-500 mb-3">
          {present.length === 1 ? "This dimension" : "Each dimension"} across{" "}
          <span className="text-slate-300">{scopeText}</span>.
        </p>
        <div className={`grid gap-4 ${present.length > 1 ? "sm:grid-cols-2" : ""}`}>
          {present.map(({ meta, ts }) => (
            <div key={meta.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-semibold">{meta.name}</h3>
                <span className="text-2xl font-bold tabular-nums">
                  {ts.track_score != null ? (ts.track_score * 100).toFixed(1) : "—"}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                {ts.n != null ? `${ts.n.toLocaleString()} test cases` : "all languages"}
                {section.weights[meta.key] != null && present.length > 1 && (
                  <> · {weightPct(section, meta.key)} of the score</>
                )}
                {slice && !slice.translation_scoped.includes(meta.key) && (
                  <> · all {langName(slice.language_tag)} translations</>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-2 mb-3 leading-relaxed">{meta.blurb}</p>
              <Link to={evalFor(meta.key)} className="text-xs text-indigo-300 hover:underline">
                Browse evaluations →
              </Link>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold mb-1">Where the score comes from</h2>
          <p className="text-xs text-slate-500">
            Every test case is recorded with the specific outcome it earned, not just
            pass/fail — inventing a verse, quoting the right verse from the wrong
            translation, and quoting a real verse without citing it are different
            behaviours worth different amounts. Counts are for{" "}
            <span className="text-slate-300">{scopeText}</span>.
          </p>
        </div>
        {present.map(({ meta, ts }) => (
          <div key={meta.key} className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
            <div className="flex items-baseline justify-between gap-3 mb-4">
              <h3 className="font-semibold">{meta.name}</h3>
              <Link to={evalFor(meta.key)} className="text-xs text-indigo-300 hover:underline">
                Browse every test case →
              </Link>
            </div>
            <DimensionBreakdown trackKey={meta.key} ts={ts} />
          </div>
        ))}
      </div>

      {/* The matrices exist to compare slices. Once one is chosen they hold a
          single column, so they'd be a wider way of saying what the cards above
          already say — the filter replaces them rather than emptying them. */}
      {slice ? (
        <p className="text-xs text-slate-500">
          Showing one translation.{" "}
          <button
            onClick={() => setVersionId(null)}
            className="text-indigo-300 hover:underline"
          >
            Show every translation
          </button>{" "}
          to compare them side by side.
        </p>
      ) : (
        <>
          {langCols.length > 0 && (
            <SliceTable
              runId={runId}
              section={section}
              heading="Scores by language"
              note={
                present.length > 1
                  ? "Click any score to read the test cases behind it. The Overall row blends both dimensions, the same way the leaderboard does."
                  : "Click any score to read the test cases behind it. Nothing here asks for a particular translation, so there is one column per language; each quotation is checked against every translation of its language."
              }
              tracks={tracks}
              cols={langCols}
              overall={present.length > 1 ? (c) => blendForSlice(section, scoreAt(c)) : undefined}
            />
          )}
          {verCols.length > 0 && (
            <SliceTable
              runId={runId}
              section={section}
              heading="Scores by Bible translation"
              note="Both dimensions name a translation in their prompts, so both are scored on every translation tested — one asking for a verse the edition contains, the other for a reference it doesn't. Click any score to read the test cases behind it."
              tracks={tracks}
              cols={verCols}
            />
          )}
        </>
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <Link to="/methodology" className="text-slate-400 hover:underline">
          How scoring works →
        </Link>
        <Link
          to={modelHref(section.key === "main" ? EXTENDED : MAIN, runId)}
          className="text-indigo-300 hover:underline"
        >
          {section.key === "main"
            ? "This model on the Extended Benchmark (beta) →"
            : "← This model on the scored benchmark"}
        </Link>
      </div>
    </div>
  );
}

/**
 * Which translations this section can be filtered to. Where the section has a
 * dimension that varies by translation, every translation is an option. Where it
 * doesn't (the Extended board), all of a language's translations would produce
 * the identical figure, so the list collapses to one per language — named by the
 * translation its prompts were actually built from.
 */
function translationOptions(section: Section, slices: SummarySlice[]): SummarySlice[] {
  const varies = slices.some((sl) =>
    section.tracks.some((t) => sl.translation_scoped.includes(t.key)),
  );
  const usable = slices.filter((sl) => section.tracks.some((t) => sl.tracks[t.key]));
  if (varies) return usable;
  const seen = new Set<string>();
  return usable.filter((sl) => !seen.has(sl.language_tag) && seen.add(sl.language_tag));
}

function TranslationFilter({
  options,
  value,
  onChange,
  slice,
  section,
}: {
  options: SummarySlice[];
  value: number | null;
  onChange: (v: number | null) => void;
  slice: SummarySlice | null;
  section: Section;
}) {
  // Grouped by language so a long list stays navigable.
  const byLang = new Map<string, SummarySlice[]>();
  for (const o of options) {
    byLang.set(o.language_tag, [...(byLang.get(o.language_tag) ?? []), o]);
  }
  const langs = orderLanguages([...byLang.keys()]);
  const langScoped = slice
    ? section.tracks.filter((t) => slice.language_scoped.includes(t.key))
    : [];
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">
          <span className="text-xs uppercase tracking-wide text-slate-400 mr-2">Translation</span>
          <select
            className="bg-white/[0.06] border border-white/10 rounded-md px-3 py-1.5 text-sm"
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">All translations</option>
            {langs.map((l) => (
              <optgroup key={l} label={langName(l)}>
                {(byLang.get(l) ?? []).map((o) => (
                  <option key={o.version_id} value={o.version_id}>
                    {o.version_abbrev}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        {value != null && (
          <button
            onClick={() => onChange(null)}
            className="text-xs text-slate-400 hover:text-white underline"
          >
            Clear
          </button>
        )}
      </div>
      <p className="text-xs text-slate-500 mt-2 leading-relaxed">
        {value == null ? (
          <>Every score on this page covers all translations. Pick one to narrow the whole page —
          the score, the loss breakdown, the outcome counts and the test-case links all follow.</>
        ) : langScoped.length > 0 ? (
          <>
            Every figure below is for this translation.{" "}
            {langScoped.map((t) => t.name).join(" and ")}{" "}
            {langScoped.length === 1 ? "names" : "name"} no translation in its prompts, so{" "}
            {langScoped.length === 1 ? "it is" : "they are"} narrowed to{" "}
            {slice ? langName(slice.language_tag) : "the language"} instead — the same figure for
            every translation of that language.
          </>
        ) : (
          <>Every figure below is for this translation.</>
        )}
      </p>
    </div>
  );
}

function weightPct(section: Section, key: string): string {
  const total = Object.values(section.weights).reduce((a, b) => a + b, 0);
  return `${Math.round((100 * (section.weights[key] ?? 0)) / total)}%`;
}

// One dimension × slice heat matrix. Every populated cell links to the raw test
// cases for exactly that (dimension, slice) subset.
function SliceTable({
  runId,
  section,
  heading,
  note,
  tracks,
  cols,
  overall,
}: {
  runId: string;
  section: Section;
  heading: string;
  note: string;
  tracks: Record<string, TrackSummary>;
  cols: Slice[];
  overall?: (s: Slice) => number | undefined;
}) {
  const present = sectionTracks(section, (k) => tracks[k]);
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
            {present.map(({ meta, ts }) => (
              <tr key={meta.key} className="border-t border-white/5">
                <td className="sticky left-0 z-10 bg-[#0b1020] px-3 py-3">
                  <Link to={evalHref(runId, meta.key)} className="font-medium hover:underline">
                    {meta.name}
                  </Link>
                </td>
                {cols.map((c) => (
                  <HeatCell
                    key={c.key}
                    value={sliceScore(ts, c)}
                    title={`${meta.name} · ${c.label} — read these test cases`}
                    href={evalHref(runId, meta.key, c)}
                  />
                ))}
              </tr>
            ))}
            {overall && (
              <tr className="border-t border-white/10 bg-white/[0.02]">
                <td className="sticky left-0 z-10 bg-[#11162a] px-3 py-3 font-medium">
                  Overall (both dimensions)
                </td>
                {cols.map((c) => (
                  <HeatCell key={c.key} value={overall(c)} title={`Overall score · ${c.label}`} />
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ModelDetail() {
  return <Report section={MAIN} />;
}

export function ExtendedModelDetail() {
  return <Report section={EXTENDED} />;
}
