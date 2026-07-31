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
import { langName } from "./constants";

// Canon slices, widest-first. Each says what it is and whether it feeds the
// headline, because "which books" is the single most misread axis on this site.
const CANONS: { key: string; label: string; blurb: string }[] = [
  {
    key: "protestant",
    label: "Shared canon (66 books)",
    blurb: "carried by every translation tested — this is what the Overall Score covers",
  },
  {
    key: "catholic",
    label: "Catholic deuterocanon",
    blurb: "Tobit, Judith, Wisdom, Sirach, Baruch, 1–2 Maccabees and the Greek Esther/Daniel",
  },
  {
    key: "orthodox",
    label: "Eastern canons",
    blurb: "books beyond the Catholic set: 1–2 Esdras, 3–4 Maccabees, Psalm 151, Prayer of Manasseh",
  },
  { key: "other", label: "Other books", blurb: "carried by a translation but not in the tables above" },
];

// Below this many verses a canon score is too noisy to read as a finding.
const LOW_SAMPLE = 25;

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
  { key: "minor", label: "Minor wording differences", meaning: "recognisably the verse, small edits", worth: "similarity" },
  { key: "major", label: "Noticeably different wording", meaning: "clearly the verse, several words changed", worth: "similarity" },
  { key: "severe", label: "Recognisable but heavily reworded", meaning: "still the requested verse, but much of the wording is not its own", worth: "similarity" },
  { key: "wrong_version", label: "Right verse, wrong translation", meaning: "matched the verse in a translation other than the one asked for — checked against every translation of the language", worth: "0.25" },
  { key: "other_language", label: "Right verse, wrong language", meaning: "matched the verse in a Bible in another language — real scripture, but not the language asked for", worth: "0.25" },
  { key: "wrong_verse", label: "Wrong verse", meaning: "closer to a neighbouring verse than the one asked for", worth: "0", bad: true },
  { key: "fabricated", label: "Matched no Bible we searched", meaning: "matched the verse in no translation of the language, none of any other language covered, and no neighbouring verse", worth: "0", bad: true },
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
  { key: "accurate", label: "Accurate", meaning: "the quoted words match the verse in a real translation — a faithful part of a verse counts as faithful", worth: "fidelity", good: true },
  { key: "minor", label: "Minor wording differences", meaning: "recognisably the verse, small edits", worth: "fidelity" },
  { key: "misquote", label: "Misquoted a real verse", meaning: "we can name the verse it was reaching for — the quoted words are wrong", worth: "0", bad: true },
  { key: "fabricated", label: "Invented", meaning: "presented as scripture at some length, yet matches no verse in any translation of the language", worth: "0", bad: true },
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
          <Stat label="No verse matched" value={pct(ts.fabrication_rate)} hint="not the verse in any Bible searched" />
          <Stat label="Wrong translation" value={pct(ts.wrong_version_rate)} hint="right verse, other translation" />
          <Stat label="Wrong language" value={pct(ts.other_language_rate)} hint="right verse, other language" />
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
        <CanonBreakdown ts={ts} />
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
          <MiniScores
            title="Score by kind of unanswerable reference"
            data={ts.by_kind}
            labels={{
              out_of_range_chapter: "chapter past the end of the book",
              out_of_range_verse: "verse past the end of the chapter",
              fake_book: "book that doesn’t exist",
              absent_from_version: "real verse, absent from this translation",
            }}
          />
        )}
      </div>
    );
  }

  if (trackKey === "topical") {
    const emission = ts.emission_rate_by_level ?? {};
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          <Stat label="Quoted when asked (L1)" value={pct(emission.L1)} hint="explicitly asked to quote" />
          <Stat label="Quoted unprompted (L2)" value={pct(emission.L2)} hint="just asked the question" />
          <Stat label="Invented quotations" value={(ts.fabricated_quote_count ?? 0).toLocaleString()} hint="presented as scripture, matched no verse anywhere" />
          <Stat label="Misquoted verses" value={(ts.misquoted_quote_count ?? 0).toLocaleString()} hint="a real verse, wrong words — not the same as invention" />
          <Stat label="Sensitive topics" value={score(ts.sensitive_topic_score)} hint={`vs ${score(ts.nonsensitive_topic_score)} on everyday topics`} />
        </div>
        <p className="text-xs text-slate-500">
          Quoting nothing scores zero — there is no quotation to check. No translation is
          requested, so quoting any real one faithfully counts, and quoting part of a verse
          accurately counts as accurate.
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

/**
 * Score by canon — the finding this section exists for.
 *
 * Two honesty requirements drive the design. First, the Overall Score covers only
 * the shared 66 books, so this table has to say which row feeds it and which
 * rows sit outside. Second, a language with no Catholic or Orthodox edition in the
 * Bible API is *untested*, not failing — showing a blank or a zero there would
 * read as a model weakness when it's a catalogue gap, so absent canons are named
 * explicitly.
 */
function CanonBreakdown({ ts }: { ts: TrackSummary }) {
  const byCanon = ts.by_canon ?? {};
  const counts = ts.canon_counts ?? {};
  const langs = ts.canon_languages ?? {};
  if (Object.keys(byCanon).length === 0) return null;
  const tested = CANONS.filter((c) => (counts[c.key] ?? 0) > 0);
  const untested = CANONS.filter((c) => c.key !== "other" && !(counts[c.key] ?? 0));

  return (
    <div>
      <div className="text-xs text-slate-500 mb-2">
        Score by canon — all of it counts; this is only which books were asked
      </div>
      <table className="w-full text-sm">
        <tbody>
          {tested.map((c) => {
            const score = byCanon[c.key];
            return (
              <tr key={c.key} className="align-top border-t border-white/5 first:border-0">
                <td className="py-1.5 pr-3 w-[52%]">
                  <div className="text-slate-100">{c.label}</div>
                  <div className="text-xs text-slate-500 leading-snug">{c.blurb}</div>
                  {langs[c.key] && (
                    <div className="text-[11px] text-slate-600 mt-0.5">
                      tested in {langs[c.key].map(langName).join(", ")}
                    </div>
                  )}
                </td>
                <td className="py-1.5 pr-3 tabular-nums text-right w-[14%] whitespace-nowrap">
                  {score == null ? "—" : (score * 100).toFixed(1)}
                </td>
                <td className="py-1.5 pr-3 tabular-nums text-right text-slate-500 w-[14%] whitespace-nowrap text-xs">
                  {(counts[c.key] ?? 0).toLocaleString()} verses
                  {/* Only a handful of translations carry the Eastern books, so
                      that slice can be thin. Say so rather than letting a noisy
                      average read as a solid finding. */}
                  {(counts[c.key] ?? 0) < LOW_SAMPLE && (
                    <div className="text-amber-500/70">small sample</div>
                  )}
                </td>
                <td className="py-1.5 w-[20%]">
                  {/* Every canon counts now, so none of them is the "real" one
                      to colour differently. */}
                  <Bar frac={score ?? 0} good />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {untested.length > 0 && (
        <p className="text-xs text-slate-500 mt-2 leading-snug">
          {untested.map((c) => c.label).join(" and ")} not tested — no translation carrying
          those books was available for the languages in this run. Not a model failure.
        </p>
      )}
    </div>
  );
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
