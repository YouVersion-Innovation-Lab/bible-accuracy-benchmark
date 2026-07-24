import { Link, Outlet } from "react-router-dom";
import { langName } from "./constants";
import { useFilters } from "./filterContext";

export function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link to="/" className="flex items-center gap-3 no-underline">
            <span className="text-xl font-bold tracking-tight">Bible Accuracy Benchmark</span>
          </Link>
          <HeaderFilters />
          <nav className="ml-auto flex gap-6 text-sm text-slate-300">
            <Link to="/" className="hover:text-white no-underline">
              Leaderboard
            </Link>
            <Link to="/methodology" className="hover:text-white no-underline">
              Methodology
            </Link>
            <a
              href="https://github.com/YouVersion-Innovation-Lab/bible-accuracy-benchmark"
              className="hover:text-white no-underline"
            >
              GitHub
            </a>
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-8">
        <Outlet />
      </main>

      <footer className="border-t border-white/10 text-xs text-slate-400">
        <div className="max-w-6xl mx-auto px-6 py-5 space-y-1">
          <p>
            A project of{" "}
            <a href="https://www.youversion.com" className="underline">
              YouVersion
            </a>
            . Scripture text shown for criticism, comment, and research.
          </p>
        </div>
      </footer>
    </div>
  );
}

// Global language + Bible-version filter. Lives inline in the header so a
// selection persists across every page (leaderboard, model detail, evaluations).
function HeaderFilters() {
  const { lang, version, setLang, setVersion, languages, versionsByLang } = useFilters();
  const langVersions = lang ? (versionsByLang.get(lang) ?? []) : [];
  const sel =
    "bg-white/[0.06] border border-white/10 rounded px-2 py-1 text-xs disabled:opacity-40";
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="uppercase tracking-wide text-slate-500">Filter</span>
      <select
        aria-label="Language"
        className={sel}
        value={lang ?? ""}
        onChange={(e) => setLang(e.target.value || null)}
      >
        <option value="">All languages</option>
        {languages.map((l) => (
          <option key={l} value={l}>
            {langName(l)}
          </option>
        ))}
      </select>
      <select
        aria-label="Bible version"
        className={sel}
        value={version ?? ""}
        disabled={!lang || langVersions.length <= 1}
        onChange={(e) => setVersion(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">All versions</option>
        {langVersions.map((v) => (
          <option key={v.version_id} value={v.version_id}>
            {v.version_abbrev}
          </option>
        ))}
      </select>
      {(lang || version != null) && (
        <button
          className="text-slate-400 underline hover:text-white"
          onClick={() => setLang(null)}
        >
          Clear
        </button>
      )}
    </div>
  );
}
