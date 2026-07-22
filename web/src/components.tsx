import type { ReactNode } from "react";

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

export function SensitiveTag() {
  return (
    <span className="ml-2 rounded bg-amber-500/15 text-amber-300 text-[10px] px-1.5 py-0.5 align-middle">
      sensitive topic
    </span>
  );
}
