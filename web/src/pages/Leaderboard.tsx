import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LeaderboardEntry } from "../api";
import { ErrorMsg, Loading, ScoreBadge } from "../components";
import { heatColor, langName, orderLanguages } from "../constants";
import { useAsync } from "../hooks";

export function Leaderboard() {
  const { data, error, loading } = useAsync(() => api.leaderboard(), []);
  const [sortLang, setSortLang] = useState<string | null>(null); // null = overall

  const languages = useMemo(() => {
    if (!data) return [];
    const tags = new Set<string>();
    data.entries.forEach((e) => Object.keys(e.by_language || {}).forEach((t) => tags.add(t)));
    return orderLanguages([...tags]);
  }, [data]);

  const rows = useMemo(() => {
    if (!data) return [];
    const sorted = [...data.entries];
    sorted.sort((a, b) => scoreFor(b, sortLang) - scoreFor(a, sortLang));
    return sorted;
  }, [data, sortLang]);

  return (
    <div>
      <section className="mb-8 max-w-3xl">
        <h1 className="text-3xl font-bold mb-3">How accurately do LLMs quote the Bible?</h1>
        <p className="text-slate-300 leading-relaxed">
          Every score is produced by deterministic comparison against the actual verse text of the
          cited translation — never by an AI judge. The headline is an overall Bible Accuracy Score;
          the columns show how faithfully each model quotes scripture in each language.
        </p>
      </section>

      {loading && <Loading />}
      {error && <ErrorMsg error={error} />}
      {data && data.entries.length === 0 && (
        <p className="text-slate-400">No published results yet.</p>
      )}

      {data && data.entries.length > 0 && (
        <>
          <LeaderCards entries={data.entries} languages={languages} />

          <div className="mt-8 overflow-x-auto rounded-xl border border-white/10">
            <table className="text-sm border-collapse">
              <thead className="bg-white/[0.04] text-slate-300">
                <tr>
                  <th className="sticky left-0 z-20 bg-[#11162a] text-left font-medium px-3 py-3 w-8">
                    #
                  </th>
                  <th className="sticky left-8 z-20 bg-[#11162a] text-left font-medium px-3 py-3 min-w-56">
                    Model
                  </th>
                  <SortableTh
                    label="Bible Accuracy"
                    active={sortLang === null}
                    onClick={() => setSortLang(null)}
                    sticky
                  />
                  {languages.map((lang) => (
                    <SortableTh
                      key={lang}
                      label={langName(lang)}
                      active={sortLang === lang}
                      onClick={() => setSortLang(lang)}
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
                      <Link
                        to={`/models/${encodeURIComponent(e.run_id)}`}
                        className="font-medium hover:underline"
                      >
                        {e.model_label}
                      </Link>
                      <div className="text-xs text-slate-500">
                        {e.provider_host}
                        {e.run_version ? ` · ${e.run_version}` : ""}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <ScoreBadge score={e.headline_score} />
                    </td>
                    {languages.map((lang) => (
                      <HeatCell key={lang} value={e.by_language?.[lang]} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Click a column header to sort. Language columns show direct-quote accuracy (0–100) for
            that language; the Bible Accuracy Score also folds in topical quoting and misquote
            resistance. Grey = not run for that model.
          </p>
        </>
      )}
    </div>
  );
}

function scoreFor(e: LeaderboardEntry, lang: string | null): number {
  if (lang === null) return e.headline_score ?? -1;
  const v = e.by_language?.[lang];
  return v == null ? -1 : v * 100;
}

function SortableTh({
  label,
  active,
  onClick,
  sticky,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  sticky?: boolean;
}) {
  return (
    <th
      onClick={onClick}
      className={`px-3 py-3 text-center font-medium cursor-pointer whitespace-nowrap hover:text-white ${
        active ? "text-white" : ""
      } ${sticky ? "" : ""}`}
      title={`Sort by ${label}`}
    >
      {label} {active ? "▼" : ""}
    </th>
  );
}

function HeatCell({ value }: { value: number | undefined }) {
  const { bg, fg } = heatColor(value);
  return (
    <td className="px-3 py-3 text-center tabular-nums" style={{ background: bg, color: fg }}>
      {value == null ? "—" : (value * 100).toFixed(0)}
    </td>
  );
}

function LeaderCards({
  entries,
  languages,
}: {
  entries: LeaderboardEntry[];
  languages: string[];
}) {
  const best = [...entries].sort((a, b) => (b.headline_score ?? 0) - (a.headline_score ?? 0))[0];
  const mostResistant = [...entries].sort(
    (a, b) => (b.by_track?.adversarial ?? 0) - (a.by_track?.adversarial ?? 0),
  )[0];
  // Widest coverage = highest minimum across languages (strong everywhere, not just English).
  const widest = [...entries].sort((a, b) => minLang(b, languages) - minLang(a, languages))[0];

  const cards = [
    { title: "Most accurate overall", e: best, val: best?.headline_score, suffix: "" },
    {
      title: "Most resistant to misquoting",
      e: mostResistant,
      val: (mostResistant?.by_track?.adversarial ?? 0) * 100,
      suffix: "",
    },
    {
      title: "Strongest across languages",
      e: widest,
      val: minLang(widest, languages),
      suffix: " min",
    },
  ];
  return (
    <div className="grid sm:grid-cols-3 gap-4">
      {cards.map((c) => (
        <div key={c.title} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div className="text-xs text-slate-400 uppercase tracking-wide">{c.title}</div>
          {c.e ? (
            <>
              <Link
                to={`/models/${encodeURIComponent(c.e.run_id)}`}
                className="text-lg font-semibold hover:underline block mt-1"
              >
                {c.e.model_label}
              </Link>
              <div className="text-2xl font-bold tabular-nums mt-1">
                {c.val != null ? c.val.toFixed(1) : "—"}
                <span className="text-sm text-slate-500">{c.suffix}</span>
              </div>
            </>
          ) : (
            <div className="text-slate-500 mt-2">—</div>
          )}
        </div>
      ))}
    </div>
  );
}

function minLang(e: LeaderboardEntry | undefined, languages: string[]): number {
  if (!e) return 0;
  const vals = languages.map((l) => e.by_language?.[l]).filter((v): v is number => v != null);
  return vals.length ? Math.min(...vals) * 100 : 0;
}
