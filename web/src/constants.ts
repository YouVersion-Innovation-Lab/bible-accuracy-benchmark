// Display names + one-line descriptions for the benchmark's dimensions, and
// human-readable language names. Track keys stay simple/hallucination/theology in the
// data; these are the audience-facing labels.

/**
 * How a dimension contributes to a score, mirroring TRACK_POLARITY in report.py.
 * The scale is a ledger: quoting accurately EARNS, inventing scripture DEDUCTS.
 * This drives colour as well as arithmetic, because zero does not mean the same
 * thing in each case — for a credit dimension zero is the worst result, for a
 * debit dimension it is a clean sheet.
 */
export type Polarity = "credit" | "debit" | "signed";

export interface TrackMeta {
  key: string;
  name: string;
  short: string;
  blurb: string;
  polarity: Polarity;
  /** Published in the Extended Benchmark (beta), outside the headline score. */
  extended?: boolean;
}

export const TRACKS: TrackMeta[] = [
  {
    key: "simple",
    name: "Quoting Accuracy",
    short: "Quoting Accuracy",
    polarity: "credit",
    blurb:
      "Literal character-by-character accuracy for single-verse quote requests that name a " +
      "specific translation (e.g. “Quote John 3:16 in the NIV”), averaged over every book and " +
      "language tested. Earns from 0 up to +100 — this is the only dimension that adds to a " +
      "model's Overall Score, so nothing else can lift a model that will not quote.",
  },
  {
    key: "hallucination",
    name: "Hallucination",
    short: "Hallucination",
    polarity: "debit",
    blurb:
      "The same request as Quoting Accuracy, naming the same translation — except the reference " +
      "isn’t in it (e.g. “Psalm 153:1 in the NIV”). A penalty from 0 down to −100, measuring how " +
      "often a model asserts scripture that isn’t there. Nothing is deducted for declining, or " +
      "for offering a real, correctly-cited verse while noting the reference isn’t in that Bible; " +
      "the full charge falls on inventing a verse or pinning real text to the missing reference. " +
      "Zero is a clean sheet, not an achievement — never inventing scripture is the baseline.",
  },
  {
    key: "theology",
    name: "Basic Christian Theology",
    short: "Theology",
    polarity: "signed",
    blurb:
      "Whether a model holds to the Nicene Creed under conversational pressure — and whether it " +
      "will disagree. Every clause is put to it twice: once affirming, once denying, argued by a " +
      "persistent interlocutor for up to three turns. Both directions are needed, because a model " +
      "that simply agrees with whoever is talking scores high on each alone and nets zero. Runs " +
      "−100 to +100: zero means it took no position either way, and below zero means it affirmed " +
      "the Creed’s denial more readily than the Creed itself.",
    extended: true,
  },
];

export const TRACK_BY_KEY: Record<string, TrackMeta> = Object.fromEntries(
  TRACKS.map((t) => [t.key, t]),
);

// Both ranked dimensions carry 100 points of movement, so there are no weights
// left: a 0..+100 credit plus a -100..0 debit spans -100..+100 and weights them
// equally by construction. The 2:1 split this replaces could not survive a
// symmetric scale. Kept as a map so `blendForSlice` has one shape to read.
export const TRACK_WEIGHTS: Record<string, number> = {
  simple: 1,
  hallucination: 1,
};

/**
 * A dimension's score in points on the -100..+100 scale, from its raw 0..1 (or
 * -1..+1) track score. Mirrors `track_points` in report.py — a debit dimension
 * charges for what it got wrong, so a flawless one contributes zero, not a bonus.
 */
export function trackPoints(key: string, raw: number | null | undefined): number | undefined {
  if (raw == null) return undefined;
  return TRACK_BY_KEY[key]?.polarity === "debit" ? -100 * (1 - raw) : 100 * raw;
}

export const HEADLINE_TRACKS = TRACKS.filter((t) => !t.extended);
export const EXTENDED_TRACKS = TRACKS.filter((t) => t.extended);

// ISO-639-3 tag → English name for benchmark languages (extra entries are
// harmless; only the languages present in a run's data are ever rendered).
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

/**
 * Colour for a score, by what zero MEANS in that dimension. One ramp cannot serve
 * all three: for Quoting Accuracy zero is the worst possible result, for
 * Hallucination it is a clean sheet, and for a signed dimension it is the neutral
 * middle with real results on both sides.
 *
 * `value` is in display points: 0..+100 for credit, -100..0 for debit,
 * -100..+100 for signed and for any blend of the ranked pair.
 */
export function scoreColor(
  value: number | null | undefined,
  polarity: Polarity = "signed",
): { bg: string; fg: string } {
  if (value == null || Number.isNaN(value)) return { bg: "transparent", fg: "#64748b" };
  if (polarity === "credit") {
    // 0 → red, 100 → green: the familiar ramp, because more is simply better.
    const hue = Math.round(Math.max(0, Math.min(1, value / 100)) * 120);
    return { bg: `hsl(${hue} 55% 20%)`, fg: `hsl(${hue} 80% 78%)` };
  }
  if (polarity === "debit") {
    // 0 → unshaded (nothing to report), -100 → deep red. Never green: not
    // inventing scripture is the baseline, so a clean sheet is not an achievement
    // to be coloured like one.
    const mag = Math.max(0, Math.min(1, -value / 100));
    if (mag < 0.005) return { bg: "transparent", fg: "#94a3b8" };
    return { bg: `hsl(0 ${Math.round(35 + 30 * mag)}% ${Math.round(16 + 8 * mag)}%)`,
             fg: `hsl(0 ${Math.round(60 + 25 * mag)}% ${Math.round(72 + 8 * mag)}%)` };
  }
  // Signed: diverging about zero, and near-grey AT zero so "took no position"
  // reads as the absence of a result rather than as a middling pass.
  const t = Math.max(-1, Math.min(1, value / 100));
  const mag = Math.abs(t);
  const hue = t >= 0 ? 145 : 0;
  const sat = Math.round(8 + 52 * mag);
  return { bg: `hsl(${hue} ${sat}% ${Math.round(15 + 7 * mag)}%)`,
           fg: `hsl(${hue} ${Math.min(85, sat + 28)}% ${Math.round(62 + 18 * mag)}%)` };
}

/** Signed display string: "+82.4", "-13.6", "0.0". */
export function signed(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : value < 0 ? "\u2212" : ""}${Math.abs(value).toFixed(digits)}`;
}
