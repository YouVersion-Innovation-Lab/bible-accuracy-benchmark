/**
 * "Show your work" panels: for each test case, how the deterministic scorer
 * arrived at its number.
 *
 * Every value rendered here comes from the run's stored scoring record — nothing
 * is recomputed in the browser — so what you read is exactly what was scored.
 * The scoring constants below mirror the Python thresholds; they're shown only to
 * explain which branch a case took.
 */
import type { ReactNode } from "react";
import type { CallMeta, EvalItem, QuoteVerdict } from "./api";
import { SensitiveTag } from "./components";
import { wordDiff, type DiffPart } from "./diff";

// Mirrors of the Python constants, for explaining a branch (not for computing).
const SIM = { nearPerfect: 0.995, minor: 0.95, major: 0.75, severe: 0.6 };
const QUOTE_SIM = { accurate: 0.98, minor: 0.9 };

/* ------------------------------------------------------------------ shared */

export function Verdict({ item }: { item: EvalItem }) {
  const pct = item.score == null ? null : Math.round(item.score * 100);
  return (
    <span
      className={`text-xs rounded px-2 py-0.5 whitespace-nowrap font-medium ${
        item.passed ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"
      }`}
    >
      {item.passed ? "Pass" : "Fail"}
      {pct != null ? ` · ${pct}/100` : ""}
    </span>
  );
}

/** One numbered step in a derivation. */
function Step({ n, label, children }: { n: number; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <div className="shrink-0 w-5 h-5 rounded-full bg-white/10 text-[11px] text-slate-300 grid place-items-center mt-0.5">
        {n}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
        <div className="text-sm text-slate-200 mt-0.5">{children}</div>
      </div>
    </div>
  );
}

/** The arithmetic that produced the final number. */
function Result({ formula, value }: { formula: string; value: number | null | undefined }) {
  return (
    <div className="rounded-lg bg-indigo-500/10 border border-indigo-400/20 px-3 py-2 flex items-baseline justify-between gap-3 flex-wrap">
      <code className="text-xs text-indigo-200">{formula}</code>
      <span className="text-sm font-semibold text-white">
        score {value == null ? "—" : value.toFixed(3)}
      </span>
    </div>
  );
}

function Num({ children }: { children: ReactNode }) {
  return <code className="text-indigo-200">{children}</code>;
}

function Flag({ on, children }: { on?: boolean; children: ReactNode }) {
  return (
    <span
      className={`text-[11px] rounded px-1.5 py-0.5 ${
        on ? "bg-white/10 text-slate-200" : "bg-white/[0.03] text-slate-500 line-through"
      }`}
    >
      {children}
    </span>
  );
}

function Work({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 space-y-3">
      <div className="text-xs font-medium text-slate-400">How this score was derived</div>
      {children}
    </div>
  );
}

/** Collapsed raw evidence: exact prompt, full response, call metadata. */
function RawDetails({ item }: { item: EvalItem }) {
  const c: CallMeta = item.call ?? {};
  const meta: [string, unknown][] = [
    ["finish_reason", c.finish_reason],
    ["model_served", c.model_served],
    ["provider", c.provider],
    ["input_tokens", c.input_tokens],
    ["output_tokens", c.output_tokens],
    ["reasoning_tokens", c.reasoning_tokens],
    ["refusal", c.refusal],
    ["response_id", c.response_id],
    ["error", c.error],
    ["item_id", item.id],
    ["scoring_version", item.scoring_version],
  ];
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      <Details label="Prompt sent">
        <pre className="whitespace-pre-wrap text-slate-300 text-sm font-sans">{item.prompt}</pre>
      </Details>
      <Details label="Full response">
        <pre className="whitespace-pre-wrap text-slate-300 text-sm font-sans">
          {item.response_text || "(empty)"}
        </pre>
      </Details>
      <Details label="Call metadata">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs font-mono">
          {meta
            .filter(([, v]) => v != null && v !== "")
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-slate-500">{k}</dt>
                <dd className="text-slate-300 break-all">{String(v)}</dd>
              </div>
            ))}
        </dl>
      </Details>
    </div>
  );
}

function Details({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="cursor-pointer text-slate-400 hover:text-slate-200 select-none">
        <span className="group-open:hidden">▸</span>
        <span className="hidden group-open:inline">▾</span> {label}
      </summary>
      <div className="mt-2 mb-1 rounded-lg bg-black/30 border border-white/5 p-3 max-h-80 overflow-auto">
        {children}
      </div>
    </details>
  );
}

function Shell({
  head,
  children,
  item,
}: {
  head: ReactNode;
  children: ReactNode;
  item: EvalItem;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        {head}
        <Verdict item={item} />
      </div>
      {children}
      <RawDetails item={item} />
    </div>
  );
}

/* --------------------------------------------------- Direct Quotation */

function gradeExplanation(item: EvalItem): string {
  const sim = item.qer == null ? null : 1 - item.qer;
  switch (item.grade) {
    case "perfect":
      return "byte-identical to the verse after Unicode normalization";
    case "near_perfect":
      return `similarity ≥ ${SIM.nearPerfect} (a stray character at most)`;
    case "minor":
      return `similarity ${sim?.toFixed(3)} is in the minor band (≥ ${SIM.minor})`;
    case "major":
      return `similarity ${sim?.toFixed(3)} is in the noticeably-different band (≥ ${SIM.major})`;
    case "severe":
      return `similarity ${sim?.toFixed(3)} still identifies the requested verse (≥ ${SIM.severe}), but much of the wording is not its own`;
    case "wrong_version":
      return "matches this verse in a different translation — every translation of the language was checked";
    case "other_language":
      return "matches this verse in a Bible in another language — real scripture, but not the language asked for";
    case "wrong_verse":
      return "closer to a neighbouring verse than to the one asked for";
    case "fabricated":
      return "matched no Bible searched — not this verse in any translation of the language, nor in any other language covered, nor a neighbouring verse";
    case "no_attempt":
      return "no gradeable quote attempt (declined, or nothing verse-like)";
    default:
      return "";
  }
}

function scoreRule(item: EvalItem): string {
  switch (item.grade) {
    case "perfect":
      return "perfect → 1.0";
    case "near_perfect":
      return "near_perfect → 0.98";
    case "minor":
    case "major":
    case "severe":
      return `1 − QER = 1 − ${item.qer?.toFixed(4)}`;
    case "wrong_version":
      return "wrong_version → 0.25";
    case "other_language":
      return "other_language → 0.25";
    default:
      return `${item.grade} → 0`;
  }
}

// Which canon a verse's book belongs to. Only shown when it isn't the shared 66,
// because that's the case a reader needs flagged: it's scored, but separately.
const CANON_TAGS: Record<string, string> = {
  catholic: "Catholic deuterocanon",
  orthodox: "Eastern canon",
  other: "outside the standard canons",
};

function CanonTag({ canon }: { canon: string }) {
  const label = CANON_TAGS[canon] ?? canon;
  return (
    <span className="ml-2 align-middle rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide bg-amber-400/10 text-amber-200 border border-amber-400/20">
      {label}
    </span>
  );
}

export function SimpleWork({ item }: { item: EvalItem }) {
  const { left, right } = wordDiff(item.expected_text ?? "", item.response_text ?? "");
  const ops = item.edit_ops ?? {};
  const opTotal = (ops.insert ?? 0) + (ops.delete ?? 0) + (ops.replace ?? 0);
  return (
    <Shell
      item={item}
      head={
        <div>
          <div className="font-mono text-sm text-white">
            {item.reference}
            <span className="text-slate-500">
              {" "}
              · {item.version_abbrev} · {item.language_tag}
              {item.tier ? ` · ${item.tier}` : ""}
            </span>
            {item.canon && item.canon !== "protestant" && <CanonTag canon={item.canon} />}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Asked for this exact verse in this exact translation.
            {item.canon && item.canon !== "protestant" && (
              <>
                {" "}This book is outside the 66 every translation shares, so it is scored in its
                own canon slice and not in the Overall Score.
              </>
            )}
          </div>
        </div>
      }
    >
      <div className="grid md:grid-cols-2 gap-4 text-sm">
        <Side title="Expected (the actual verse)" parts={left} />
        <Side title="What the model returned" parts={right} />
      </div>

      <Work>
        <Step n={1} label="Isolate the quote attempt">
          {item.extraction_method === "trivial" ? (
            <>
              The whole response was treated as the attempt, after stripping quote marks and any
              reference line (<Num>method: trivial</Num>).
            </>
          ) : (
            <>
              The verse was located inside a longer response by best-window alignment (
              <Num>method: window</Num>), so the quote still gets full accuracy credit but{" "}
              <Num>format_ok</Num> is false.
            </>
          )}
        </Step>
        <Step n={2} label="Measure the difference">
          Character-level edit distance ÷ verse length ={" "}
          <Num>QER {item.qer?.toFixed(4)}</Num> → similarity{" "}
          <Num>{item.qer == null ? "—" : (1 - item.qer).toFixed(4)}</Num>
          {opTotal > 0 && (
            <span className="text-slate-400">
              {" "}
              ({ops.replace ?? 0} replaced, {ops.insert ?? 0} inserted, {ops.delete ?? 0} deleted)
            </span>
          )}
          {item.wer != null && <span className="text-slate-500"> · word-level WER {item.wer.toFixed(3)}</span>}
        </Step>
        <Step n={3} label="Rule out a different verse or translation">
          <div className="space-y-0.5">
            <div>
              Same verse, other translations: best match{" "}
              <Num>{item.best_distractor ? item.best_distractor.similarity.toFixed(3) : "—"}</Num>
              {item.best_distractor && <span className="text-slate-500"> (id {item.best_distractor.key})</span>}
            </div>
            <div>
              Neighbouring verses: best match{" "}
              <Num>{item.best_neighbor ? item.best_neighbor.similarity.toFixed(3) : "—"}</Num>
              {item.best_neighbor && <span className="text-slate-500"> ({item.best_neighbor.usfm})</span>}
            </div>
          </div>
        </Step>
        <Step n={4} label="Grade">
          <span className="text-white font-medium">{item.grade}</span>
          <span className="text-slate-400"> — {gradeExplanation(item)}</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Flag on={item.verbatim_strict}>verbatim (strict)</Flag>
            <Flag on={item.verbatim_loose}>verbatim (loose)</Flag>
            <Flag on={item.format_ok}>clean format</Flag>
            {item.overquote && <Flag on>quoted more than asked</Flag>}
            {item.ground_truth_drift && <Flag on>source verse changed since sampling</Flag>}
          </div>
        </Step>
        <Result formula={scoreRule(item)} value={item.score} />
      </Work>
    </Shell>
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
              p.kind === "add"
                ? "bg-emerald-500/20 text-emerald-200 rounded px-0.5"
                : p.kind === "del"
                  ? "bg-rose-500/20 text-rose-200 rounded px-0.5 line-through"
                  : "text-slate-300"
            }
          >
            {p.text}
          </span>
        ))}
      </p>
    </div>
  );
}

/* ----------------------------------------- Scripture in Answers (topical) */

const QUOTE_LABELS: Record<string, string> = {
  accurate: "matches the cited verse",
  minor: "small wording differences",
  mismatch: "doesn’t match the verse it cites",
  misattributed: "real verse text, wrong reference",
  fabricated_ref: "cited a reference that doesn’t exist",
  fabricated: "matches no verse in any tested translation",
  unverifiable: "couldn’t be checked",
};

function quoteScoreRule(q: QuoteVerdict): string {
  if (q.classification === "accurate") return `similarity ≥ ${QUOTE_SIM.accurate} → 1.0`;
  if (q.classification === "minor")
    return `in the ${QUOTE_SIM.minor}–${QUOTE_SIM.accurate} band → credited as ${q.score.toFixed(3)}`;
  return "→ 0";
}

function QuoteRow({ q, i }: { q: QuoteVerdict; i: number }) {
  return (
    <div className="rounded-lg bg-black/20 border border-white/5 p-2.5 space-y-1">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500">#{i + 1}</span>
          <span className={`text-[11px] rounded px-1.5 py-0.5 ${badgeClass(q.classification)}`}>
            {q.classification}
          </span>
          {q.unquoted && (
            <span className="text-[11px] rounded px-1.5 py-0.5 bg-white/5 text-slate-400">
              no quote marks
            </span>
          )}
        </div>
        <code className="text-xs text-indigo-200">
          sim {q.similarity.toFixed(3)} → {q.score.toFixed(3)}
        </code>
      </div>
      <p className="font-serif text-sm text-slate-200">“{q.quote}”</p>
      <div className="text-xs text-slate-500">
        {QUOTE_LABELS[q.classification] ?? q.classification} · {quoteScoreRule(q)}
        {q.cited_usfm && <> · model cited <code className="text-slate-400">{q.cited_usfm}</code></>}
        {q.matched_usfm && q.matched_usfm !== q.cited_usfm && (
          <> · actually matches <code className="text-slate-400">{q.matched_usfm}</code></>
        )}
      </div>
    </div>
  );
}

export function TopicalWork({ item }: { item: EvalItem }) {
  const quotes = item.quotes ?? [];
  const scores = quotes.map((q) => q.score);
  const mean = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  return (
    <Shell
      item={item}
      head={
        <div>
          <div className="text-sm text-white">
            <span className="font-medium">{item.topic_name}</span>
            <span className="text-slate-500">
              {" "}
              · {item.elicitation_level === "L1" ? "L1 · asked to quote" : "L2 · quoting optional"} ·{" "}
              {item.language_tag}
            </span>
            {item.sensitive && <SensitiveTag />}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Scored on the accuracy of whatever scripture the model chose to quote.
          </div>
        </div>
      }
    >
      {quotes.length > 0 ? (
        <div>
          <div className="text-xs text-slate-500 mb-1.5">
            Scripture detected in the response ({quotes.length}
            {item.n_accurate != null ? `, ${item.n_accurate} accurate` : ""})
          </div>
          <div className="space-y-1.5">
            {quotes.map((q, i) => (
              <QuoteRow key={i} q={q} i={i} />
            ))}
          </div>
        </div>
      ) : (
        <div className="text-sm text-slate-400 rounded-lg bg-black/20 border border-white/5 p-3">
          No quoted scripture was detected in this response.
        </div>
      )}

      <Work>
        <Step n={1} label="Find every span presented as scripture">
          {quotes.length === 0 ? (
            <>
              Nothing quoted — no quotation marks, no blockquote, and no sentence matching a real
              verse closely enough (≥ {QUOTE_SIM.minor}) to count as an unmarked quote.
            </>
          ) : (
            <>
              Found <Num>{quotes.length}</Num> verifiable quotation
              {quotes.length === 1 ? "" : "s"}, each checked against the verse it cites — or, when
              uncited, against every verse of the translation.
            </>
          )}
        </Step>
        <Step n={2} label="Accuracy — mean of the per-quote scores">
          {mean == null ? (
            <span className="text-slate-400">Not applicable: nothing was quoted.</span>
          ) : (
            <>
              <Num>
                ({scores.map((s) => s.toFixed(2)).join(" + ")}) ÷ {scores.length} ={" "}
                {(item.accuracy ?? mean).toFixed(4)}
              </Num>
              {item.grades && Object.keys(item.grades).length > 0 && (
                <div className="text-xs text-slate-500 mt-1">
                  {Object.entries(item.grades)
                    .map(([g, n]) => `${n} ${g}`)
                    .join(" · ")}
                </div>
              )}
            </>
          )}
        </Step>
        <Step n={3} label="Emission — did it quote at all?">
          {item.emission ? (
            <>
              <Num>1.0</Num> — at least one verifiable quotation.
            </>
          ) : (
            <>
              <Num>0.0</Num> — quoting nothing scores zero, at both levels. Paraphrase and bare
              references don’t count; only a quotation can be checked for accuracy.
            </>
          )}
        </Step>
        {(item.n_fabricated_refs ?? 0) > 0 && (
          <Step n={4} label="Fabricated references">
            <Num>{item.n_fabricated_refs}</Num> cited reference
            {item.n_fabricated_refs === 1 ? "" : "s"} resolved to no real verse
            {item.fabricated_refs && item.fabricated_refs.length > 0 && (
              <span className="text-slate-500"> ({item.fabricated_refs.join(", ")})</span>
            )}
            .
          </Step>
        )}
        <Result
          formula={`accuracy ${item.accuracy == null ? "—" : item.accuracy.toFixed(4)} × emission ${(item.emission ?? 0).toFixed(1)}`}
          value={item.score}
        />
      </Work>
    </Shell>
  );
}

/* ------------------------------------ Hallucination Resistance (phantom) */

const PHANTOM_LADDER: { key: string; label: string; score: string; why: string }[] = [
  { key: "refused", label: "Declined to quote", score: "1.0", why: "answered without presenting any scripture" },
  {
    key: "declined_with_substitute",
    label: "Declined + offered a real, cited verse",
    score: "1.0",
    why: "said the reference isn’t in the Bible and every quote was real and correctly attributed",
  },
  {
    key: "substitute_no_disclaimer",
    label: "Real cited verse, but no warning",
    score: "0.5",
    why: "quoted a real verse under its own correct reference, but never said the request doesn’t exist",
  },
  {
    key: "unreferenced_substitute",
    label: "Real scripture, no reference or warning",
    score: "0",
    why: "recited real scripture with neither a reference nor a correction, leaving the fake reference unchallenged",
  },
  {
    key: "misattributed_real_verse",
    label: "Real verse pinned to the fake reference",
    score: "0",
    why: "attached genuine verse text to a reference that doesn’t exist",
  },
  { key: "fabricated_text", label: "Invented verse text", score: "0", why: "produced scripture that matches nothing" },
  { key: "no_response", label: "No response at all", score: "0", why: "silence isn’t a refusal — it tells the user nothing" },
  { key: "quoted_real_verse", label: "Substituted a real verse (legacy)", score: "0", why: "pre-v0.2 outcome, kept so older runs still render" },
];

export function PhantomWork({ item }: { item: EvalItem }) {
  const quotes = item.quotes ?? [];
  const hit = PHANTOM_LADDER.find((r) => r.key === item.outcome);
  return (
    <Shell
      item={item}
      head={
        <div>
          <div className="font-mono text-sm text-white">
            {item.reference}
            <span className="text-slate-500"> · {item.language_tag}</span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            {item.kind === "absent_from_version" ? (
              <>
                <span className="text-slate-300">This verse is real</span> — it just isn’t in the
                translation we asked for. {item.version_abbrev} does not include this book
                {item.absent_source_abbrev ? `; ${item.absent_source_abbrev} does` : ""}. The
                model should say the book sits outside this translation’s canon; quoting it
                while saying so is fully correct.
              </>
            ) : (
              <>
                This reference does not exist ({(item.kind ?? "").replace(/_/g, " ")}). No
                translation is requested — the model should decline, ideally saying why.
              </>
            )}
          </div>
        </div>
      }
    >
      <div>
        <div className="text-xs text-slate-500 mb-1">What the model returned</div>
        <p className="text-sm text-slate-200 whitespace-pre-wrap rounded-lg bg-black/20 border border-white/5 p-3">
          {item.response_text || <em className="text-slate-500">(empty)</em>}
        </p>
      </div>

      {quotes.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs text-slate-500">Scripture detected in the response</div>
          {quotes.map((q, i) => (
            <QuoteRow key={i} q={q} i={i} />
          ))}
        </div>
      )}

      <Work>
        <Step n={1} label="Did it say the reference isn’t real?">
          {item.denial_signaled ? (
            <>
              <span className="text-emerald-300">Yes</span> — the response contains a phrase that
              deterministically signals the reference doesn’t exist (“no such chapter”, “only has N
              chapters”, “not in the Bible”, matched per language).
            </>
          ) : (
            <>
              <span className="text-rose-300">No</span> — no recognised “that isn’t in the Bible”
              phrase was found.
            </>
          )}
        </Step>
        <Step n={2} label="Did it present any scripture?">
          {quotes.length === 0 ? (
            <>
              <Num>0</Num> quotations detected.
            </>
          ) : (
            <>
              <Num>{quotes.length}</Num> quotation{quotes.length === 1 ? "" : "s"} detected —{" "}
              {quotes.every((q) => q.matched_usfm) ? "all matched real verses" : "at least one matched no real verse"}
              {quotes.some((q) => q.cited_usfm && q.matched_usfm && q.cited_usfm !== q.matched_usfm) &&
                ", and at least one carried the wrong reference"}
              .
            </>
          )}
        </Step>
        <Step n={3} label="Outcome">
          <div className="space-y-1">
            {PHANTOM_LADDER.filter((r) => r.key !== "quoted_real_verse" || item.outcome === r.key).map(
              (r) => {
                const active = r.key === item.outcome;
                return (
                  <div
                    key={r.key}
                    className={`flex items-baseline gap-2 rounded px-2 py-1 ${
                      active ? "bg-white/10" : "opacity-40"
                    }`}
                  >
                    <code className="text-xs text-indigo-200 w-8 shrink-0">{r.score}</code>
                    <div className="min-w-0">
                      <span className={active ? "text-white" : "text-slate-400"}>{r.label}</span>
                      {active && <span className="text-slate-400 text-xs"> — {r.why}</span>}
                    </div>
                  </div>
                );
              },
            )}
          </div>
        </Step>
        <Result formula={hit ? `outcome: ${item.outcome}` : `outcome: ${item.outcome ?? "—"}`} value={item.score} />
      </Work>
    </Shell>
  );
}

function badgeClass(c: string): string {
  if (c === "accurate") return "bg-emerald-500/15 text-emerald-300";
  if (c === "minor") return "bg-amber-500/15 text-amber-300";
  if (c === "unverifiable") return "bg-white/10 text-slate-300";
  return "bg-rose-500/15 text-rose-300";
}
