// Display names + one-line descriptions for the three benchmark tracks, and
// human-readable language names. Track keys stay simple/topical/adversarial in
// the data; these are the audience-facing labels.

export interface TrackMeta {
  key: string;
  name: string;
  short: string;
  blurb: string;
}

export const TRACKS: TrackMeta[] = [
  {
    key: "simple",
    name: "Direct Quotation",
    short: "Direct Quotation",
    blurb:
      "Literal character-by-character accuracy for single-verse quote requests that name a " +
      "specific translation (e.g. “Quote John 3:16 in the NIV”), averaged over every book and " +
      "language tested.",
  },
  {
    key: "topical",
    name: "Scripture in Answers",
    short: "Scripture in Answers",
    blurb:
      "For open questions (“What does the Bible say about anxiety?”), the share of the verses the " +
      "model quotes that match a real translation character-for-character. Quoting nothing scores " +
      "zero.",
  },
  {
    key: "phantom",
    name: "Hallucination Resistance",
    short: "Hallucination Resistance",
    blurb:
      "For requests to quote a reference that does not exist (e.g. “Psalm 180:1”), the share of " +
      "prompts where the model quoted nothing — declining instead of inventing a verse or " +
      "substituting a real one.",
  },
];

export const TRACK_BY_KEY: Record<string, TrackMeta> = Object.fromEntries(
  TRACKS.map((t) => [t.key, t]),
);

// Composite weights — must match TRACK_WEIGHTS in report.py. Used to blend the
// per-track, per-language scores into an "overall score" for each language.
export const TRACK_WEIGHTS: Record<string, number> = {
  simple: 0.5,
  topical: 0.25,
  phantom: 0.25,
};

// ISO-639-3 tag → English name, for the ~28 benchmark languages.
export const LANGUAGE_NAMES: Record<string, string> = {
  eng: "English", spa: "Spanish", por: "Portuguese", fra: "French", deu: "German",
  ita: "Italian", nld: "Dutch", ron: "Romanian", pol: "Polish", rus: "Russian",
  ukr: "Ukrainian", ell: "Greek", arb: "Arabic", pes: "Persian", tur: "Turkish",
  swh: "Swahili", amh: "Amharic", hin: "Hindi", ben: "Bengali", tam: "Tamil",
  tel: "Telugu", ind: "Indonesian", tgl: "Tagalog", vie: "Vietnamese", tha: "Thai",
  kor: "Korean", jpn: "Japanese", zho: "Chinese",
};

export function langName(tag: string): string {
  return LANGUAGE_NAMES[tag] ?? tag;
}

// Canonical language ordering for columns (English first, then by the spec order).
const LANG_ORDER = Object.keys(LANGUAGE_NAMES);
export function orderLanguages(tags: string[]): string[] {
  const known = LANG_ORDER.filter((t) => tags.includes(t));
  const extra = tags.filter((t) => !LANG_ORDER.includes(t)).sort();
  return [...known, ...extra];
}

// Heat-map color for a 0..1 score → HSL red→green, matching ScoreBadge.
export function heatColor(score: number | null | undefined): { bg: string; fg: string } {
  if (score == null) return { bg: "transparent", fg: "#64748b" };
  const hue = Math.round(score * 120);
  return { bg: `hsl(${hue} 55% 20%)`, fg: `hsl(${hue} 80% 78%)` };
}
