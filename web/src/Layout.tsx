import { Link, NavLink, Outlet } from "react-router-dom";

/** A board tab. `end` on "/" so the model pages under it don't light it up. */
function Tab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `no-underline rounded-t-lg px-4 py-2 -mb-4 border-b-2 font-medium ${
          isActive
            ? "border-indigo-400 text-white bg-white/[0.04]"
            : "border-transparent text-slate-400 hover:text-slate-200"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link to="/" className="flex items-center gap-3 no-underline">
            <span className="text-xl font-bold tracking-tight">Bible Accuracy Benchmark</span>
          </Link>
          {/* Two boards, as tabs — they are the site. Methodology and the repo sit
              apart from them, smaller: a reader chooses between the boards, not
              between a board and a prose page. */}
          <nav className="flex flex-wrap items-center gap-x-1 gap-y-2 text-sm">
            <Tab to="/">Bible Accuracy Leaderboard</Tab>
            <Tab to="/extended">
              Theology Leaderboard
              <span className="ml-1.5 rounded bg-amber-400/15 text-amber-300 text-[10px] uppercase tracking-wide px-1 py-0.5 align-middle">
                beta
              </span>
            </Tab>
          </nav>
          <div className="ml-auto flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-400">
            <Link to="/methodology" className="hover:text-white no-underline">
              Methodology
            </Link>
            <a
              href="https://github.com/YouVersion-Innovation-Lab/bible-accuracy-benchmark"
              className="hover:text-white no-underline"
            >
              GitHub
            </a>
          </div>
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
