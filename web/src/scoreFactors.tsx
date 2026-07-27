/**
 * "What dropped this score" — the credit-report view of a model's result.
 *
 * A score alone tells you where a model ranks but not what to fix. Each factor
 * here is a named behaviour with the exact number of points it cost, ranked
 * biggest-lever first, so the list reads as a diagnosis rather than a verdict.
 *
 * The numbers reconcile: they sum to (100 − Overall Score) by construction, and
 * the panel shows that sum so a reader can check it. That property is the whole
 * reason to trust the list — a decomposition that doesn't add up leaves you
 * unable to tell which entry is wrong.
 *
 * One distinction this exists to draw: a provider's content filter refusing to
 * emit verbatim scripture (Google's RECITATION) costs the same points as a model
 * declining, but it is not the same event. Folding them together reports a
 * platform policy as a model's choice.
 */
import type { Summary } from "./api";
import { TRACKS } from "./constants";

type FactorCopy = {
  label: string;
  detail: string;
  /** Attributable to the provider/platform rather than the model's knowledge. */
  external?: boolean;
};

const FACTOR_COPY: Record<string, FactorCopy> = {
  // Cross-dimension
  blocked_by_provider: {
    label: "The provider blocked its own answer",
    detail:
      "The model was cut off by a content filter before it could quote — Google's RECITATION filter does this to verbatim scripture. No verse reached the user, so it scores zero, but the cause is the platform's safety layer, not the model failing to know the text.",
    external: true,
  },

  // Direct Quotation grades
  near_perfect: {
    label: "Off by a character or two",
    detail:
      "The verse quoted with a trivial difference — a punctuation or spacing variant. Worth 0.98, so it costs almost nothing; listed only so the arithmetic adds up.",
  },
  minor: {
    label: "Small wording changes",
    detail: "Recognisably the right verse, with words altered, added or dropped.",
  },
  major: {
    label: "Heavily altered wording",
    detail: "The right verse, but substantially rewritten.",
  },
  wrong_version: {
    label: "Right verse, wrong translation",
    detail:
      "Quoted the verse accurately — from a different translation than the one asked for. Scored at 0.25 because the words were real scripture, just not the requested edition.",
  },
  wrong_verse: {
    label: "Quoted a neighbouring verse",
    detail: "The text matches a verse near the one requested, not the one requested.",
  },
  fabricated: {
    label: "Invented verse text",
    detail:
      "Produced verse-shaped text matching no verse in any translation checked. The most serious failure in this dimension.",
  },
  no_attempt: {
    label: "Declined to quote",
    detail:
      "Offered no gradeable quotation when directly asked for one. Declining is a scored failure, not an exclusion — a model that won't quote can't be accurate.",
  },

  // Scripture in Answers
  no_quote: {
    label: "Answered without quoting scripture",
    detail:
      "Discussed the topic but never quoted a verse, so there was nothing to check. Paraphrase and bare references (“see Romans 12”) don't count.",
  },
  inaccurate_quotes: {
    label: "Quoted, but not accurately",
    detail:
      "Volunteered scripture whose wording doesn't match the verse in any translation of that language.",
  },

  // Hallucination Resistance outcomes
  fabricated_text: {
    label: "Invented a verse that doesn't exist",
    detail:
      "Asked for a reference no Bible contains, the model produced verse text for it. This is the failure this dimension exists to catch.",
  },
  misattributed_real_verse: {
    label: "Pinned real scripture to a fake reference",
    detail:
      "Attached genuine verse text to a reference that doesn't exist, which asserts the fake reference is real.",
  },
  unreferenced_substitute: {
    label: "Recited real scripture with no citation or warning",
    detail:
      "Quoted a genuine verse but neither cited it nor said the requested reference doesn't exist, leaving the user to assume it was the verse they asked for.",
  },
  substitute_no_disclaimer: {
    label: "Offered a real verse without flagging the problem",
    detail:
      "Cited a genuine verse correctly but never told the user the reference they asked for doesn't exist. Half credit — helpful, but it leaves a false belief in place.",
  },
  no_response: {
    label: "Returned nothing at all",
    detail:
      "An empty reply with no explanation. Silence is not a refusal: the user learns nothing about whether the verse exists.",
  },
};

function copyFor(key: string): FactorCopy {
  return (
    FACTOR_COPY[key] ?? {
      label: key.replace(/_/g, " "),
      detail: "Outcome not described in this version of the site.",
    }
  );
}

const trackName = (key: string) => TRACKS.find((t) => t.key === key)?.name ?? key;

export function ScoreFactors({ summary }: { summary: Summary }) {
  const factors = summary.score_factors ?? [];
  if (factors.length === 0) {
    // Either a flawless run, or a run scored before factors were recorded.
    // Saying nothing is right for the first and honest for the second.
    return null;
  }
  const total = factors.reduce((a, f) => a + f.points, 0);
  const worst = factors[0].points;
  // Ranked by impact, except that anything attributable to the platform rather
  // than the model is always shown even when small. It's a different KIND of
  // fact: a reader comparing two models needs to know some of the gap wasn't the
  // model's doing, and rolling that into "7 smaller factors" hides it.
  const top = factors.slice(0, 6);
  const shown = [...top, ...factors.slice(6).filter((f) => copyFor(f.key).external)];
  const rest = factors.slice(6).filter((f) => !copyFor(f.key).external);
  const restPoints = rest.reduce((a, f) => a + f.points, 0);
  const restLabels = [...new Set(rest.map((f) => copyFor(f.key).label.toLowerCase()))];

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="text-lg font-semibold">What dropped this score</h2>
        <div className="text-xs text-slate-500 tabular-nums">
          {total.toFixed(1)} points lost of 100
        </div>
      </div>
      <p className="text-xs text-slate-500 mt-1 mb-4 leading-relaxed">
        Every point between this model's score and 100, attributed to the behaviour that
        cost it and ranked by impact. The figures add up to the shortfall exactly, so the
        biggest entry is genuinely the biggest thing to fix.
      </p>

      <ol className="space-y-2.5">
        {shown.map((f) => {
          const c = copyFor(f.key);
          return (
            <li key={`${f.track}:${f.key}`} className="flex gap-3">
              <div className="w-16 shrink-0 text-right">
                <div
                  className={`text-lg font-semibold tabular-nums leading-none ${
                    c.external ? "text-sky-300" : "text-rose-200"
                  }`}
                >
                  {/* A real cost that rounds to zero at one decimal must not
                      print as "−0.0", which reads as a rendering bug. */}
                  {f.points < 0.05 ? "<0.1" : `−${f.points.toFixed(1)}`}
                </div>
                <div className="text-[10px] text-slate-600 mt-0.5">
                  {f.n.toLocaleString()} {f.n === 1 ? "case" : "cases"}
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-sm text-slate-100">{c.label}</span>
                  <span className="text-[10px] uppercase tracking-wide text-slate-600">
                    {trackName(f.track)}
                  </span>
                  {c.external && (
                    <span className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide bg-sky-400/10 text-sky-300 border border-sky-400/20">
                      platform, not model
                    </span>
                  )}
                </div>
                <div
                  className={`mt-1 h-1 rounded overflow-hidden ${
                    c.external ? "bg-sky-400/10" : "bg-rose-400/10"
                  }`}
                >
                  <div
                    className={`h-full ${c.external ? "bg-sky-400/60" : "bg-rose-400/60"}`}
                    style={{ width: `${Math.max((f.points / worst) * 100, 2)}%` }}
                  />
                </div>
                <p className="text-xs text-slate-500 mt-1 leading-snug">{c.detail}</p>
              </div>
            </li>
          );
        })}
      </ol>

      {rest.length > 0 && (
        <div className="text-xs text-slate-500 mt-3">
          + {rest.length} smaller {rest.length === 1 ? "factor" : "factors"} worth{" "}
          <span className="tabular-nums">{restPoints.toFixed(1)}</span> points together:{" "}
          {restLabels.join(", ")}.
        </div>
      )}

      <div className="text-xs text-slate-500 mt-4 pt-3 border-t border-white/5 tabular-nums">
        {total.toFixed(1)} lost + {(summary.headline_score ?? 0).toFixed(1)} scored = 100
      </div>
    </div>
  );
}
