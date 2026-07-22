import { Link, Outlet } from "react-router-dom";
import { SCOPE_NOTE } from "./api";

export function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3 no-underline">
            <span className="text-xl font-bold tracking-tight">
              Bible Accuracy Benchmark
            </span>
          </Link>
          <nav className="flex gap-6 text-sm text-slate-300">
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
          <p className="max-w-3xl">{SCOPE_NOTE}</p>
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
