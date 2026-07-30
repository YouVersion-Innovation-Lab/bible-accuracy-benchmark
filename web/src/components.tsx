import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { heatColor } from "./constants";

export function ScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-slate-500">—</span>;
  const hue = Math.round((score / 100) * 120); // red→green
  return (
    <span
      className="inline-block rounded-md px-2 py-0.5 font-mono font-semibold tabular-nums"
      style={{ background: `hsl(${hue} 60% 22%)`, color: `hsl(${hue} 85% 78%)` }}
    >
      {score.toFixed(1)}
    </span>
  );
}

// Heat-map matrix cell for a 0..1 score (leaderboard + model-detail tables).
// Given `href`, the whole cell links to the test cases behind the number.
// `divider` marks the first cell of a column group.
export function HeatCell({
  value,
  title,
  href,
  divider,
}: {
  value: number | undefined;
  title?: string;
  href?: string;
  divider?: boolean;
}) {
  const { bg, fg } = heatColor(value);
  const linked = href != null && value != null;
  return (
    <td
      className={`text-center tabular-nums ${divider ? "border-l border-white/10" : ""}`}
      style={{ background: bg, color: fg }}
      title={title}
    >
      {linked ? (
        <Link
          to={href}
          className="block px-3 py-3 no-underline hover:brightness-125"
          style={{ color: fg }}
        >
          {(value * 100).toFixed(0)}
        </Link>
      ) : (
        <span className="block px-3 py-3">{value == null ? "—" : (value * 100).toFixed(0)}</span>
      )}
    </td>
  );
}

export function Pct({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="text-slate-500">—</span>;
  return <span className="tabular-nums">{(v * 100).toFixed(1)}%</span>;
}

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5">
      <h3 className="text-sm font-semibold text-slate-300 mb-3">{title}</h3>
      {children}
    </div>
  );
}

export function Loading() {
  return <p className="text-slate-400 animate-pulse">Loading…</p>;
}

export function ErrorMsg({ error }: { error: string }) {
  return <p className="text-rose-400">Error: {error}</p>;
}

// Why the Extended Benchmark is separate, said once and reused wherever its
// numbers appear. A beta board that doesn't say what's provisional about it is
// just a second leaderboard with a smaller font.
export function BetaNotice() {
  return (
    <div className="rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-4 py-3 text-sm">
      <span className="rounded bg-amber-400/15 text-amber-300 text-[10px] uppercase tracking-wide px-1.5 py-0.5 align-middle">
        beta
      </span>{" "}
      <span className="text-amber-100/90">
        Not part of any model's Overall Score.
      </span>{" "}
      <span className="text-slate-400">
        These dimensions are measured on every model and reported in full, but held out of the
        ranking while their scoring is still being settled. Treat the numbers as evidence for
        discussion, not as a verdict.
      </span>
    </div>
  );
}

export function SensitiveTag() {
  return (
    <span className="ml-2 rounded bg-amber-500/15 text-amber-300 text-[10px] px-1.5 py-0.5 align-middle">
      sensitive topic
    </span>
  );
}
