import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry } from "../api";
import { BetaNotice, ErrorMsg, HeatCell, Loading, ScoreBadge } from "../components";
import { useAsync } from "../hooks";
import { EXTENDED, MAIN, blendForSlice, boardSlices, modelHref, type Section } from "../sections";
import { sliceScore, type Slice } from "../slices";

// A data column: one slice, scored in display points per model.
interface Col {
  key: string;
  label: string;
  title?: string;
  get: (e: LeaderboardEntry) => number | undefined;
  /** Dimensions with no data for this slice — named so a partial cell says so. */
  missing: (e: LeaderboardEntry) => string[];
}

const OVERALL = "overall";

export function Board({ section }: { section: Section }) {
  const { data, error, loading } = useAsync(() => api.leaderboard(), []);
  const [sortKey, setSortKey] = useState<string>(OVERALL);
  const [benchVer, setBenchVer] = useState<string | null>(null);

  // Benchmark generations present in the data, newest first. The board shows one
  // generation at a time (rankings stay apples-to-apples); default to the newest.
  const benchVersions = useMemo(() => {
    if (!data) return [];
    const s = new Set(data.entries.map((e) => e.run_version).filter((v): v is string => !!v));
    return [...s].sort((a, b) => verNum(b) - verNum(a));
  }, [data]);
  const activeVer = benchVer ?? benchVersions[0] ?? null;

  const entries = useMemo(
    () => (data ? data.entries.filter((e) => !activeVer || e.run_version === activeVer) : []),
    [data, activeVer],
  );

  // One column per slice, always all of them: no filter to set, nothing hidden
  // behind one.
  const cols: Col[] = useMemo(() => {
    const slices = boardSlices(
      section,
      entries.flatMap((e) => section.tracks.map((t) => e.tracks_detail?.[t.key])),
    );
    return slices.map((s: Slice) => ({
      key: s.key,
      label: s.label,
      title: `${section.title} · ${s.label}`,
      get: (e: LeaderboardEntry) =>
        blendForSlice(section, (t) => sliceScore(e.tracks_detail?.[t], s)),
      // Seven of the eighteen editions carry no hallucination items, so their cell
      // is a credit with nothing charged against it. That is a real gap in what was
      // measured, not a clean sheet, and one number cannot show the difference —
      // so the cell says which dimension is missing rather than letting a
      // single-dimension figure pass as a complete ledger.
      missing: (e: LeaderboardEntry) =>
        section.tracks
          .filter((t) => sliceScore(e.tracks_detail?.[t.key], s) == null)
          .map((t) => t.short),
    }));
  }, [entries, section]);

  const rows = useMemo(() => {
    const col = cols.find((c) => c.key === sortKey);
    // Both are display points now, so neither needs scaling; -Infinity rather
    // than -1 for "no data", because a real score can legitimately be negative
    // and -1 would sort a genuinely bad model above a missing one.
    const val = (e: LeaderboardEntry) =>
      sortKey !== OVERALL && col
        ? (col.get(e) ?? -Infinity)
        : (section.scoreOf(e) ?? -Infinity);
    return [...entries].sort((a, b) => val(b) - val(a));
  }, [entries, cols, sortKey, section]);

  return (
    <div>
      {section.beta ? <ExtendedIntro /> : <MainIntro />}

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && data.entries.length === 0 && (
        <p className="text-slate-400">No published results yet.</p>
      )}

      {data && data.entries.length > 0 && (
        <>
          <div className="mb-4 flex items-center gap-2 text-sm">
            <span className="text-xs uppercase tracking-wide text-slate-500">
              Benchmark version
            </span>
            {benchVersions.length > 1 ? (
              <select
                className="bg-white/[0.06] border border-white/10 rounded px-2 py-1 text-sm"
                value={activeVer ?? ""}
                onChange={(e) => setBenchVer(e.target.value)}
              >
                {benchVersions.map((v) => (
                  <option key={v} value={v}>
                    {v}
                    {v === benchVersions[0] ? " (latest)" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-medium">{activeVer ?? "—"}</span>
            )}
            <Link to="/methodology" className="text-xs text-slate-400 hover:underline">
              what this version tests →
            </Link>
          </div>

          {isFast(activeVer) && (
            <div className="mb-4 rounded-lg border border-sky-400/25 bg-sky-400/[0.06] px-4 py-3 text-sm">
              <span className="rounded bg-sky-400/15 text-sky-300 text-[10px] uppercase tracking-wide px-1.5 py-0.5 align-middle">
                fast pass
              </span>{" "}
              <span className="text-sky-100/90">
                About a tenth of the questions.
              </span>{" "}
              <span className="text-slate-400">
                Every language and every translation is still covered — the items are thinned
                within each language, not truncated — and the questions are a subset of the full
                run's, so these scores differ from a full run by coverage rather than by sample.
                Read them as a first look, not a final ranking: per-translation columns rest on
                only a handful of verses each.
              </span>
            </div>
          )}

          <p className="text-xs text-slate-500 mb-2">
            Every column is the same score as the one on the left — {section.composition} —
            narrowed to {section.sliceKind === "version" ? "one Bible translation" : "one language"}.
            All shown at once; scroll sideways for the rest. Click a column heading to sort by it,
            or a model to see its own breakdown.
          </p>

          <div className="mt-3 overflow-x-auto rounded-xl border border-white/10">
            <table className="text-sm border-collapse">
              <thead className="bg-white/[0.04] text-slate-300">
                <tr>
                  <th
                    rowSpan={2}
                    className="sticky left-0 z-20 bg-[#11162a] text-left font-medium px-3 py-3 w-8"
                  >
                    #
                  </th>
                  <th
                    rowSpan={2}
                    className="sticky left-8 z-20 bg-[#11162a] text-left font-medium px-3 py-3 min-w-56"
                  >
                    Model
                  </th>
                  <SortableTh
                    label={section.scoreLabel}
                    title={`${section.composition}, across every language`}
                    active={sortKey === OVERALL}
                    onClick={() => setSortKey(OVERALL)}
                    rowSpan={2}
                  />
                  <GroupTh span={cols.length} label={section.sliceGroup} />
                </tr>
                <tr>
                  {cols.map((c) => (
                    <SortableTh
                      key={c.key}
                      label={c.label}
                      title={c.title}
                      active={sortKey === c.key}
                      onClick={() => setSortKey(c.key)}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((e, i) => (
                  <tr key={e.run_id} className="border-t border-white/5">
                    <td className="sticky left-0 z-10 bg-[#0b1020] px-3 py-3 text-slate-500 tabular-nums">
                      {i + 1}
                    </td>
                    <td className="sticky left-8 z-10 bg-[#0b1020] px-3 py-3">
                      <Link to={modelHref(section, e.run_id)} className="font-medium hover:underline">
                        {e.model_label}
                      </Link>
                      <div className="text-xs text-slate-500">
                        {e.provider_host}
                        {e.run_version ? ` · ${e.run_version}` : ""}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <ScoreBadge score={section.scoreOf(e)} />
                    </td>
                    {cols.map((c) => {
                      const gaps = c.missing(e);
                      return (
                        <HeatCell
                          key={c.key}
                          value={c.get(e)}
                          title={
                            `${e.model_label} · ${c.label}` +
                            (gaps.length ? ` — not measured: ${gaps.join(", ")}` : "")
                          }
                          partial={gaps.length > 0}
                        />
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {section.sliceKind === "version" && (
            <p className="text-xs text-slate-500 mt-2">
              <sup>†</sup> Quoting Accuracy only — this edition carries no hallucination items,
              because those prompts ask a named Bible for a reference it does not contain, and
              only eleven of the eighteen editions have a set of their own. Nothing is charged
              against these figures, so they are not comparable with a full column.
            </p>
          )}

          <CrossLink section={section} />
        </>
      )}
    </div>
  );
}

function MainIntro() {
  return (
    <section className="mb-8 text-slate-300 leading-normal space-y-3">
      <h1 className="text-3xl font-bold text-white">How accurately do LLMs quote the Bible?</h1>
      <div>
        <p>
          A public, deterministic benchmark of how faithfully LLMs quote the Bible. Scores run{" "}
          <strong>−100 to +100</strong>, and are a ledger of two dimensions:
        </p>
        <ul className="list-disc pl-5 mt-1 space-y-0.5">
          <li>
            <strong>Quoting Accuracy</strong> <span className="text-emerald-300/80">(earns up to
            +100)</span> — asked for a specific verse, does it reproduce the exact text?
          </li>
          <li>
            <strong>Hallucination</strong> <span className="text-rose-300/80">(deducts up to
            −100)</span> — asked for a verse that doesn't exist, does it decline or invent one?
          </li>
        </ul>
        <p className="mt-1">
          The two add up, so every score on this board can be checked by eye. A model that quotes
          faithfully and never invents approaches <strong>+100</strong>; one that invents as often
          as it quotes lands near <strong>zero</strong> — and so does one that simply never quotes,
          because declining earns nothing.{" "}
          <strong>Nothing scores above zero without accurately quoting scripture.</strong>
        </p>
      </div>
      <p className="text-slate-400">
        This board rates only the accuracy of quoted scripture — it does not score or rate the
        theological positions or theological accuracy of a response. Theological alignment is
        measured, but it is reported on the{" "}
        <Link to="/extended" className="underline">
          Theology Leaderboard
        </Link>{" "}
        and counts toward no model's Bible Accuracy Score.
      </p>
    </section>
  );
}

function ExtendedIntro() {
  return (
    <section className="mb-8 text-slate-300 leading-normal space-y-3">
      <h1 className="text-3xl font-bold text-white">Theology Leaderboard — Beta</h1>
      <BetaNotice />
      <div>
        <p>
          The same kind of ledger as the main board, applied to a different question: does a model
          hold to the <strong>Nicene Creed</strong> — the confession most of Christianity shares —
          and will it disagree with someone pressing it to abandon a clause?
        </p>
        <p className="mt-2">
          Every clause of the Creed is put to the model twice — once affirming it, once denying it —
          and argued by a persistent interlocutor for up to three turns, in eleven languages.
        </p>
        <ul className="list-disc pl-5 mt-2 space-y-0.5">
          <li>
            <strong>Propensity to Defend the Creed</strong>{" "}
            <span className="text-emerald-300/80">(earns up to +100)</span> — will it say a clause
            is true when simply asked?
          </li>
          <li>
            <strong>Propensity to Contradict the Creed</strong>{" "}
            <span className="text-rose-300/80">(deducts up to −100)</span> — can it be talked into
            affirming a denial?
          </li>
        </ul>
        <p className="mt-2">
          Both directions are needed because either alone rewards the wrong thing. A model that
          simply agrees with whoever is talking looks devout when you only ask it to affirm — and
          looks heretical when you only ask it to deny. Running both makes agreeableness cancel.
        </p>
      </div>
      <p className="text-amber-200/80">
        Read <strong>zero</strong> here as <em>took no position either way</em>. Most models tested
        so far sit near it, because they answer theology by describing what different traditions
        believe rather than by holding a view — and the two dimensions tell you which kind of zero
        you are looking at. A model at <strong>+100 / −100</strong> agrees with everything put to
        it; one at <strong>0 / 0</strong> commits to nothing. Same net, opposite behaviour.
      </p>
      <p className="text-slate-400">
        Read exactly as the main board: same columns, same colours, same drill-downs, and the two
        dimensions add up the same way. None of it counts toward any model's Bible Accuracy Score.
      </p>
    </section>
  );
}

function CrossLink({ section }: { section: Section }) {
  const other = section.key === "main" ? EXTENDED : MAIN;
  return (
    <div className="mt-6 rounded-xl border border-white/10 bg-white/[0.02] p-4 text-sm">
      {section.key === "main" ? (
        <>
          <Link to={other.base || "/"} className="text-indigo-300 hover:underline font-medium">
            Theology Leaderboard — Beta →
          </Link>
          <p className="text-xs text-slate-500 mt-1">
            Whether a model holds to the Nicene Creed under pressure, and whether it will disagree —
            scored as the same credit-and-debit ledger as this board, and counting toward no
            model's Bible Accuracy Score.
          </p>
        </>
      ) : (
        <>
          <Link to="/" className="text-indigo-300 hover:underline font-medium">
            ← Back to the Bible Accuracy Benchmark
          </Link>
          <p className="text-xs text-slate-500 mt-1">
            The ranked board: {MAIN.composition}.
          </p>
        </>
      )}
    </div>
  );
}

// Numeric ordering for benchmark version strings: "v0.2", "v1.10", "v0.5-fast".
//
// A suffixed generation sorts just BELOW its full version, because it asks a
// subset of the same questions — when both exist the full run is the better
// default. Parsing only the leading digits also matters: Number("5-fast") is NaN,
// and a NaN comparator silently leaves the list unsorted, which would have
// defaulted the board to an older generation and hidden the newest one behind
// the selector.
function verNum(v: string): number {
  const bare = v.replace(/^v/i, "");
  const m = bare.match(/^(\d+)(?:\.(\d+))?/);
  if (!m) return -1;
  const num = Number(m[1]) * 1000 + Number(m[2] ?? 0);
  return m[0] === bare ? num : num - 0.5;
}

/** Is this generation a fast pass rather than a full run? */
function isFast(v: string | null): boolean {
  return !!v && /-fast$/.test(v);
}

// Heading over a block of columns. The label is sticky *inside* its own span, so
// it stays readable while you scroll through a block 18 columns wide instead of
// sitting centred somewhere off-screen.
function GroupTh({ span, label }: { span: number; label: string }) {
  if (span <= 0) return null;
  return (
    <th
      colSpan={span}
      className="px-3 pt-2 pb-1 text-left font-medium border-l border-white/10"
    >
      <span className="sticky left-[17rem] inline-block text-[11px] uppercase tracking-wide text-slate-500">
        {label}
      </span>
    </th>
  );
}

function SortableTh({
  label,
  active,
  onClick,
  title,
  rowSpan,
  divider,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  title?: string;
  rowSpan?: number;
  divider?: boolean;
}) {
  return (
    <th
      onClick={onClick}
      rowSpan={rowSpan}
      className={`px-3 py-3 text-center font-medium cursor-pointer whitespace-nowrap hover:text-white ${
        active ? "text-white" : ""
      } ${divider ? "border-l border-white/10" : ""}`}
      title={title ? `${title} — sort` : `Sort by ${label}`}
    >
      {label} {active ? "▼" : ""}
    </th>
  );
}

export function Leaderboard() {
  return <Board section={MAIN} />;
}

export function ExtendedLeaderboard() {
  return <Board section={EXTENDED} />;
}
