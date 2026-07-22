import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorMsg, Loading, ScoreBadge } from "../components";
import { useAsync } from "../hooks";

const TRACK_LABELS: Record<string, string> = {
  simple: "Simple",
  topical: "Topical",
  adversarial: "Adversarial",
};

export function Leaderboard() {
  const { data, error, loading } = useAsync(() => api.leaderboard(), []);

  return (
    <div>
      <section className="mb-8 max-w-3xl">
        <h1 className="text-3xl font-bold mb-3">How accurately do LLMs quote the Bible?</h1>
        <p className="text-slate-300 leading-relaxed">
          Every score below is produced by deterministic text comparison against the
          actual verse text of the cited translation — never by an LLM judge. Models
          are tested on direct quote requests, realistic topical questions, and
          adversarial attempts to induce misquotes, across many translations and
          languages.
        </p>
      </section>

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && data.entries.length === 0 && (
        <p className="text-slate-400">No published results yet.</p>
      )}

      {data && data.entries.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead className="bg-white/[0.04] text-slate-300">
              <tr>
                <th className="text-left font-medium px-4 py-3 w-10">#</th>
                <th className="text-left font-medium px-4 py-3">Model</th>
                <th className="text-right font-medium px-4 py-3">Bible Accuracy</th>
                <th className="text-right font-medium px-4 py-3 hidden sm:table-cell">Simple</th>
                <th className="text-right font-medium px-4 py-3 hidden sm:table-cell">Topical</th>
                <th className="text-right font-medium px-4 py-3 hidden sm:table-cell">
                  Adversarial
                </th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((e, i) => (
                <tr key={e.run_id} className="border-t border-white/5 hover:bg-white/[0.03]">
                  <td className="px-4 py-3 text-slate-500 tabular-nums">{i + 1}</td>
                  <td className="px-4 py-3">
                    <Link
                      to={`/models/${encodeURIComponent(e.run_id)}`}
                      className="font-medium hover:underline"
                    >
                      {e.model_label}
                    </Link>
                    <div className="text-xs text-slate-500">{e.provider_host}</div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <ScoreBadge score={e.headline_score} />
                  </td>
                  {["simple", "topical", "adversarial"].map((t) => (
                    <td
                      key={t}
                      className="px-4 py-3 text-right tabular-nums text-slate-300 hidden sm:table-cell"
                      title={TRACK_LABELS[t]}
                    >
                      {e.by_track[t] != null ? (e.by_track[t] * 100).toFixed(1) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
