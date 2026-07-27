/**
 * Per-dimension outcome breakdowns.
 *
 * Each dimension records *why* a test case scored what it did, not merely
 * pass/fail — "invented a verse", "quoted the right verse from the wrong
 * translation" and "quoted a real verse but never cited it" are different
 * behaviours that a single failure rate hides. The scorer has always kept them
 * apart; this surfaces them.
 *
 * Every label carries what the outcome is *worth*, so a reader can reconstruct
 * the dimension score from the table rather than taking it on trust.
 */
import type { TrackSummary } from "./api";

type Row = {
  key: string;
  label: string;
  meaning: string;
  worth?: string;
  good?: boolean;   // green — the behaviour we want
  bad?: boolean;    // red — asserting scripture that isn't there
};

/** Direct Quotation: the severity grades of the decision tree. */
const SIMPLE_GRADES: Row[] = [
  { key: "perfect", label: "Exact", meaning: "character-for-character identical to the verse", worth: "1.00", good: true },
  { key: "near_perfect", label: "Near-exact", meaning: "a stray character at most", worth: "0.98", good: true },
  { key: "minor", label: "Minor wording differences", meaning: "recognisably the verse, small edits", worth: "1 − error rate" },
  { key: "major", label: "Major wording differences", meaning: "substantially altered", worth: "1 − error rate" },
  { key: "wrong_version", label: "Right verse, wrong translation", meaning: "matched the verse in a translation other than the one asked for", worth: "0.25" },
  { key: "wrong_verse", label: "Wrong verse", meaning: "closer to a neighbouring verse than the one asked for", worth: "0", bad: true },
  { key: "fabricated", label: "Invented text", meaning: "verse-shaped text matching no candidate verse", worth: "0", bad: true },
  { key: "no_attempt", label: "Declined / no attempt", meaning: "no gradeable quotation offered", worth: "0" },
];

/** Hallucination Resistance: the outcome ladder, best to worst. */
const PHANTOM_OUTCOMES: Row[] = [
  { key: "refused", label: "Declined to quote", meaning: "answered without presenting any scripture", worth: "1.00", good: true },
  { key: "declined_with_substitute", label: "Declined, offered a real cited verse", meaning: "said the reference isn’t in the Bible, then quoted a genuine verse correctly", worth: "1.00", good: true },
  { key: "declined_noncanonical", label: "Explained it isn’t canonical", meaning: "named the source as outside the biblical canon, then quoted it", worth: "1.00", good: true },
  { key: "substitute_no_disclaimer", label: "Real cited verse, no warning", meaning: "offered a genuine verse under its own reference, but never said the request doesn’t exist", worth: "0.50" },
  { key: "unreferenced_substitute", label: "Real verse, uncited and unflagged", meaning: "recited real scripture with neither a reference nor a correction", worth: "0", bad: true },
  { key: "misattributed_real_verse", label: "Real verse pinned to the fake reference", meaning: "attached genuine verse text to a reference that doesn’t exist", worth: "0", bad: true },
  { key: "fabricated_text", label: "Invented a verse", meaning: "produced scripture matching nothing in any translation", worth: "0", bad: true },
  { key: "no_response", label: "No response at all", meaning: "returned nothing — silence is not a refusal", worth: "0", bad: true },
];

/** Scripture in Answers: per-quotation verdicts, aggregated across items. */
const TOPICAL_GRADES: Row[] = [
  { key: "accurate", label: "Accurate", meaning: "matches a real translation; credited in proportion to how much of the verse was quoted", worth: "fidelity × coverage", good: true },
  { key: "minor", label: "Minor wording differences", meaning: "recognisably the verse, small edits", worth: "fidelity × coverage" },
  { key: "misquote", label: "Misquoted", meaning: "presented as a quotation but the words don’t match the verse", worth: "0", bad: true },
  { key: "fabricated", label: "Invented", meaning: "quoted as scripture, matches no verse in any translation of the language", worth: "0", bad: true },
];

function Bar({ frac, good, bad }: { frac: number; good?: boolean; bad?: boolean }) {
  const color = good ? "bg-emerald-400/70" : bad ? "bg-rose-400/70" : "bg-amber-400/60";
  return (
    <div className="h-1.5 w-full rounded bg-white/5 overflow-hidden">
      <div className={`h-full ${color}`} style={{ width: `${Math.max(frac * 100, frac > 0 ? 1.5 : 0)}%` }} />
    </div>
  );
}

function OutcomeTable({
  rows,
  counts,
  total,
  caption,
}: {
  rows: Row[];
  counts: Record<string, number>;
  total: number;
  caption: string;
}) {
  // Anything the scorer emitted that isn't in the known list still gets shown —
  // silently dropping an outcome would misrepresent the totals.
  const extra = Object.keys(counts).filter((k) => !rows.some((r) => r.key === k));
  const all: Row[] = [
    ...rows,
    ...extra.map((k): Row => ({
      key: k,
      label: k,
      meaning: "(outcome not in this version’s ladder)",
    })),
  ];
  const present = all.filter((r) => (counts[r.key] ?? 0) > 0);
  if (present.length === 0) return null;
  return (
    <div>
      <div className="text-xs text-slate-500 mb-2">{caption}</div>
      <table className="w-full text-sm">
        <tbody>
          {present.map((r) => {
            const n = counts[r.key] ?? 0;
            const frac = total > 0 ? n / total : 0;
            return (
              <tr key={r.key} className="align-top">
                <td className="py-1.5 pr-3 w-[46%]">
                  <div className={r.good ? "text-emerald-200" : r.bad ? "text-rose-200" : "text-slate-200"}>
                    {r.label}
                  </div>
                  <div className="text-xs text-slate-500 leading-snug">{r.meaning}</div>
                </td>
                <td className="py-1.5 pr-3 w-[18%] text-xs text-slate-500 whitespace-nowrap">
                  {r.worth ? `worth ${r.worth}` : ""}
                </td>
                <td className="py-1.5 pr-3 tabular-nums text-right w-[10%] whitespace-nowrap">
                  {n.toLocaleString()}
                </td>
                <td className="py-1.5 pr-3 tabular-nums text-right text-slate-400 w-[8%] whitespace-nowrap">
                  {(frac * 100).toFixed(1)}%
                </td>
                <td className="py-1.5 w-[18%]">
                  <Bar frac={frac} good={r.good} bad={r.bad} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-white/[0.03] border border-white/5 px-3 py-2">
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-slate-400">{label}</div>
      {hint && <div className="text-[11px] text-slate-500 mt-0.5 leading-snug">{hint}</div>}
    </div>
  );
}

const pct = (v?: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const score = (v?: number | null) => (v == null ? "—" : (v * 100).toFixed(1));

export function DimensionBreakdown({ trackKey, ts }: { trackKey: string; ts: TrackSummary }) {
  const total = ts.n ?? 0;

  if (trackKey === "simple") {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat label="Exactly verbatim" value={pct(ts.verbatim_rate)} hint="identical after Unicode normalization" />
          <Stat label="Invented text" value={pct(ts.fabrication_rate)} hint="matched no candidate verse" />
          <Stat label="Wrong translation" value={pct(ts.wrong_version_rate)} hint="right verse, other translation" />
          <Stat label="Clean formatting" value={pct(ts.format_ok_rate)} hint="verse only, as asked" />
        </div>
        <OutcomeTable
          rows={SIMPLE_GRADES}
          counts={ts.grades ?? {}}
          total={total}
          caption={`How each of the ${total.toLocaleString()} quote requests was graded`}
        />
        {ts.by_tier && Object.keys(ts.by_tier).length > 0 && (
          <MiniScores title="Score by verse difficulty" data={ts.by_tier} />
        )}
      </div>
    );
  }

  if (trackKey === "phantom") {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat label="Declined" value={pct(ts.refusal_rate)} hint="quoted nothing, or named it non-canonical" />
          <Stat label="Invented a verse" value={pct(ts.hallucination_rate)} hint="the failure this dimension exists to catch" />
          <Stat label="Misattributed" value={pct(ts.misattribution_rate)} hint="real verse pinned to the fake reference" />
          <Stat label="Uncited real verse" value={pct(ts.unreferenced_rate)} hint="quoted without reference or warning" />
        </div>
        <OutcomeTable
          rows={PHANTOM_OUTCOMES}
          counts={ts.outcomes ?? {}}
          total={total}
          caption={`What the model did across ${total.toLocaleString()} requests for a verse that doesn’t exist`}
        />
        {ts.by_kind && Object.keys(ts.by_kind).length > 0 && (
          <MiniScores title="Score by kind of impossible reference" data={ts.by_kind} />
        )}
      </div>
    );
  }

  if (trackKey === "topical") {
    const emission = ts.emission_rate_by_level ?? {};
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat label="Quoted when asked (L1)" value={pct(emission.L1)} hint="explicitly asked to quote" />
          <Stat label="Quoted unprompted (L2)" value={pct(emission.L2)} hint="just asked the question" />
          <Stat label="Invented quotations" value={(ts.fabricated_quote_count ?? 0).toLocaleString()} hint="presented as scripture, matched nothing" />
          <Stat label="Sensitive topics" value={score(ts.sensitive_topic_score)} hint={`vs ${score(ts.nonsensitive_topic_score)} on everyday topics`} />
        </div>
        <p className="text-xs text-slate-500">
          Quoting nothing scores zero — there is no quotation to check. No translation is
          requested, so quoting any real one faithfully counts.
        </p>
        <OutcomeTable
          rows={TOPICAL_GRADES}
          counts={ts.quote_grades ?? {}}
          total={ts.n_quotes ?? 0}
          caption={`Every one of the ${(ts.n_quotes ?? 0).toLocaleString()} quotations the model volunteered, verified against all translations of its language`}
        />
        {ts.by_level && Object.keys(ts.by_level).length > 0 && (
          <MiniScores
            title="Score by how directly a quotation was requested"
            data={ts.by_level}
            labels={{ L1: "L1 — asked to quote", L2: "L2 — quoting optional" }}
          />
        )}
      </div>
    );
  }

  return null;
}

function MiniScores({
  title,
  data,
  labels,
}: {
  title: string;
  data: Record<string, number>;
  labels?: Record<string, string>;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <div className="text-xs text-slate-500 mb-2">{title}</div>
      <div className="flex flex-wrap gap-2">
        {entries.map(([k, v]) => (
          <div key={k} className="rounded-lg bg-white/[0.03] border border-white/5 px-2.5 py-1.5">
            <span className="text-xs text-slate-400">{labels?.[k] ?? k}</span>
            <span className="ml-2 text-sm font-medium tabular-nums">{(v * 100).toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
