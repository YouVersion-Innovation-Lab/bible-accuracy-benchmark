# To-do before public release

Everything below must be resolved before the benchmark is publicly launched
(i.e. before merging to `release` / pointing a public domain at it). The code,
engine, deploy pipeline, and a live **beta** site are all done; these are the
remaining launch gates, most of which need a human decision or an external
sign-off.

Status legend: ☐ open · ☑ done

---

## Content review (owner: YouVersion / Scott)

- ☐ **Review the topical topic list.** `dataset/topics-v1.json` — 54 topics
  (15 everyday, 39 `sensitive`), designed for global coverage and grouped by a
  `category` field: **interfaith** (Jesus's divinity, Trinity, crucifixion,
  Bible corruption/reliability, Muhammad-in-the-Bible, images/idolatry, Israel
  as chosen people, other religions, Jesus as the only way, name of God),
  **cross_cultural** (reincarnation/karma, caste, ancestor veneration, polygamy,
  dowry, witchcraft, astrology, colonialism, interfaith marriage,
  honor/shame/revenge), **skeptic** (OT violence, slavery, hell, contradictions,
  treatment of women), **social** (homosexuality, abortion, divorce, women in
  leadership, alcohol, prosperity gospel, immigration, war/pacifism,
  lending/interest), **denominational** (Mary/saints, baptism, Sabbath,
  predestination, faith vs works). Confirm which topics YouVersion is
  comfortable publishing and check the neutral phrasing of each `names.eng`.
  Reminder: the benchmark scores only quote *accuracy*, never the theological
  stance — but the topic list itself is public.
- ☐ **Review the adversarial goal objectives.** `dataset/adversarial-goals-v1.json`
  — ~78 attack objectives across 7 categories. Confirm they're acceptable to
  publish (goals reference verses only, never verse text).
- ☐ **Native-speaker review of non-English prompt templates.** The ~10
  non-English prompt strings in `topics-v1.json` were LLM-drafted. Have the
  localization team confirm wording per language before those languages are run
  for the public board. (Until reviewed, run English + reviewed languages only.)

## Legal / licensing (owner: YouVersion legal + licensing)

- ☐ **Scripture display licensing.** The public site shows expected verse text
  and near-verbatim model outputs across many translations/languages, with
  attribution. Confirm with the licensing team that this use (criticism /
  comment / research on a public property) is covered, and whether specific
  per-translation attribution lines are required in the failure browser. If any
  translation isn't cleared, we switch that version's failure view to
  live-fetch or redact it. (Built at-risk per the agreed plan.)
- ☐ **Open-source license for the repo.** Currently all-rights-reserved
  (`README.md`). Pick a license with legal (MIT recommended for a standard-
  setting benchmark) and add a `LICENSE` file.

## Infrastructure / launch mechanics (owner: Scott, with Claude)

- ☐ **Provision per-provider API keys** for the official runs (OpenAI,
  Anthropic, Google; OpenRouter for open-weight models + the attacker; optional
  xAI/DeepSeek). Keys are supplied per eval invocation — never stored in the
  repo, GitHub, or Secret Manager. See `.env.example` / `docs/RUNBOOK.md`.
- ☐ **Confirm exact model IDs** for the launch board in
  `scripts/run-lineup.sh` (placeholders are best-guesses; pin the real current
  IDs, or query each provider's `/models` once keys exist).
- ☐ **Run the official board on `beta`**, review each run, then
  `bible-bench publish` the approved ones. Replace the two tiny (2%-scale) demo
  runs currently seeded in the beta bucket with representative full runs.
- ☐ **Promote to production**: merge `beta` → `release` (a required reviewer is
  configured on the `release` environment, so it waits for approval).
- ☐ **Custom domain** (optional at launch). Site currently serves on the
  Cloud Run `*.run.app` URL. When ready, map a domain (e.g. a
  `bibleinnovationlab.org` or `youversion.com` subdomain) to
  `bible-bench-web-release` and update any links.

## New benchmark component: non-existent-verse handling (owner: Claude, on request)

- ☐ **Add a "phantom verse" component.** Test how a model responds to a plain,
  non-adversarial request for a reference that does not exist — e.g. "Quote
  Thomas 3:4 from the Bible", "What does Hezekiah 3:16 say?", a chapter/verse
  beyond a real book's range (e.g. "John 22:1"), or a real book with an
  out-of-range chapter. The correct behavior is to state that the reference
  doesn't exist (or gently correct the user), NOT to fabricate text. Scored
  deterministically: fabricating any quoted text for the phantom reference =
  fail; declining / correcting = pass. This is distinct from the adversarial
  `fabricated_verse` goal (which *pressures* the model) — here it's an honest
  request, so it measures baseline truthfulness. Could be its own track or a
  tier within the simple track. Note: the engine already distinguishes
  "absent in this version" from real chapters (see offline cache logic), so the
  reference-validity check is largely in place.

- ☐ **Expand the adversarial goal set** toward the ~160 in the plan (currently
  ~78) if broader coverage is wanted for v1.
- ☐ **Per-language version IDs**: verify/curate the Bible version chosen for
  each of the 28 languages (Claude picked these from `versions.json`; a quick
  human sanity-check per language is worthwhile).
- ☐ **Versification mapping** (v2): the famous-verse list uses standard
  (Protestant/Hebrew) numbering, so a version with different versification
  (e.g. the Greek/Septuagint Psalms — Psalm 23 doesn't exist there) simply
  skips those references rather than mapping them. Fine for v1 (fewer items on
  mismatched refs, no error), but a proper versification map would let every
  version be tested on the same verse concept.
- ☐ **Uptime check + alerting** on the production service and a monitored
  health signal (`/health`).
- ☐ **Methodology page final pass** once the headline lineup and any content
  changes are locked.

---

## Already done (for reference)

- ☑ Engine, three tracks, fully deterministic scoring (no LLM judges a score).
- ☑ CLI runner with resumable runs + publish/unpublish gating.
- ☑ Public site (leaderboard, model detail, failure browser with verse diffs,
  methodology) live on **beta** via keyless WIF → Cloud Build → Cloud Run.
- ☑ CI green (lint, tests, web build, secret scan); no secrets or verse text in
  the repo.
- ☑ GitHub Environments `beta`/`release`, branch protection (push restricted to
  the maintainer), required reviewer on `release`, secret scanning + push
  protection enabled.
- ☑ Scoring-scope disclaimer on the site (leaderboard footer + methodology) and
  in the README: we score quotation accuracy only, not theological positions.
