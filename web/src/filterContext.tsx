// Global language + Bible-version filter, shared across every page and
// persisted to localStorage so a selection sticks as you navigate (and across
// reloads). Options (languages + versions) are derived once from the leaderboard.
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { orderLanguages } from "./constants";
import { buildVersionsByLang, type VersionsByLang } from "./FilterBar";
import { useAsync } from "./hooks";

interface FilterState {
  lang: string | null;
  version: number | null;
  setLang: (l: string | null) => void;
  setVersion: (v: number | null) => void;
  languages: string[];
  versionsByLang: VersionsByLang;
}

const Ctx = createContext<FilterState | null>(null);
const LS_LANG = "bab.filter.lang";
const LS_VER = "bab.filter.version";

export function FilterProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<string | null>(
    () => localStorage.getItem(LS_LANG) || null,
  );
  const [version, setVersionState] = useState<number | null>(() => {
    const v = localStorage.getItem(LS_VER);
    return v ? Number(v) : null;
  });

  const { data } = useAsync(() => api.leaderboard(), []);
  const languages = useMemo(() => {
    const tags = new Set<string>();
    (data?.entries ?? []).forEach((e) =>
      Object.keys(e.by_language || {}).forEach((t) => tags.add(t)),
    );
    return orderLanguages([...tags]);
  }, [data]);
  const versionsByLang = useMemo(
    () => buildVersionsByLang((data?.entries ?? []).flatMap((e) => e.versions ?? [])),
    [data],
  );

  function setLang(l: string | null) {
    setLangState(l);
    setVersionState(null); // a version only means something within a language
    if (l) localStorage.setItem(LS_LANG, l);
    else localStorage.removeItem(LS_LANG);
    localStorage.removeItem(LS_VER);
  }
  function setVersion(v: number | null) {
    setVersionState(v);
    if (v != null) localStorage.setItem(LS_VER, String(v));
    else localStorage.removeItem(LS_VER);
  }

  const value: FilterState = { lang, version, setLang, setVersion, languages, versionsByLang };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFilters(): FilterState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFilters must be used within FilterProvider");
  return v;
}
