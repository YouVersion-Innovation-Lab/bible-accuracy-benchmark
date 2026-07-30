# Versification mappings

Machine-readable Paratext `.vrs` rules, vendored verbatim from the
[Copenhagen Alliance versification specification][spec] — one file per scheme:

    versification-mappings/standard-mappings/{eng,org,lxx,rso,rsc,vul}.json

Fetched 2026-07-30. Re-dumped compactly (sorted keys, no whitespace); no content
changed.

## Why these are committed rather than fetched

A benchmark result has to be reproducible years later. Fetching the mapping at
run time would make every published score depend on an external repository still
existing, unchanged, at that URL. These are 89 KB total.

## Why versification matters here

Every Bible edition YouVersion carries declares its scheme in the Core API's
`version.json` as `vrs`. Across the 18 translations this benchmark tests:

| scheme | translations |
|---|---|
| `eng` | KJV, NIV11, NLT, NRSVUE, AVD, DELUT, HINOVBSI, KRV, ARA, RVR1960, CUNPSS-Shen |
| `org` | NABRE, LSG, TB, CAV |
| `rso` | SYNO, Synod |
| `lxx` | AVM |

The same reference is **not** the same verse across schemes. The Psalms are
renumbered wholesale: `lxx`/`rso` Psalm 23 is `eng`/`org` Psalm 24, so a request
for `PSA.23.1` returns a different psalm in three of those eighteen editions —
not a shifted verse, a different psalm. `lxx.json` carries 145 Psalms mappings
doing precisely that offset.

So the benchmark picks every reference in the `eng` scheme, then translates it
into each edition's own scheme (`eng` → `org` → target) before asking for it.
Without that step a per-translation score silently compares different passages.

## Shape

Each file carries:

* `maxVerses` — `{book: [verse count per chapter]}` for that scheme.
* `mappedVerses` — `{scheme ref → org ref}`, non-identity entries only. Absent
  means the reference is identical in `org`.
* `excludedVerses`, `partialVerses` — verses some editions omit or split. Not
  used yet; relevant to a harder benchmark that probes these deliberately.

[spec]: https://github.com/Copenhagen-Alliance/versification-specification
