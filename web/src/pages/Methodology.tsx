export function Methodology() {
  return (
    <article className="prose prose-invert max-w-3xl space-y-5 leading-relaxed">
      <h1 className="text-3xl font-bold">Methodology</h1>

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
        <strong>What this measures — and what it doesn't.</strong> This benchmark scores
        only the Biblical accuracy of scripture quotations in model responses: when a
        model presents text as a quote from the Bible, is that text actually what the
        cited translation says? It does <em>not</em> score or rate the theological
        positions, doctrinal leanings, or theological accuracy of a response. A response
        may take any interpretive position and still score perfectly, as long as every
        quotation it attributes to scripture is faithful.
      </div>

      <Section title="Scoring is deterministic">
        No language model ever renders or influences a score. Every verdict comes from
        deterministic text comparison against the actual verse text of the cited
        translation, fetched at evaluation time from YouVersion's Bible API. The only
        place a language model appears is generating the attack prompts in the
        adversarial track — and even there, the judge is deterministic.
      </Section>

      <Section title="The three tracks">
        <ul className="list-disc pl-6 space-y-1">
          <li>
            <strong>Simple (50%).</strong> Direct quote requests ("Quote John 3:16 in the
            NIV") sampled across every book of the Bible, many translations, and ~28
            languages.
          </li>
          <li>
            <strong>Topical (25%).</strong> Realistic questions that elicit scripture
            ("What does the Bible say about anxiety?"), asked both with and without an
            explicit instruction to quote, spanning everyday, doctrinal, interfaith, and
            cross-cultural subjects. Scored on the accuracy of whatever the model quotes;
            a response that paraphrases or declines to quote scores zero.
          </li>
          <li>
            <strong>Adversarial (25%).</strong> An attacker model actively tries to induce
            misquotes — subtle word swaps, fabricated verses, false attributions, and
            pressure tactics. The score is the model's resistance rate.
          </li>
        </ul>
        <p className="mt-2">
          <strong>Bible Accuracy Score</strong> = 100 × (0.50 × simple + 0.25 × topical +
          0.25 × adversarial resistance). There is no path to a good score without
          willingly and accurately quoting scripture across the whole canon.
        </p>
      </Section>

      <Section title="What it takes to score well">
        <ul className="list-disc pl-6 space-y-1">
          <li>
            <strong>
              When asked what the Bible says about a topic, a model scores better by
              quoting the Bible directly than by paraphrasing or merely giving references.
            </strong>{" "}
            Only verbatim quotations are scored; a paraphrase, a summary, or a bare
            citation ("see Romans 12") earns nothing on the topical track.
          </li>
          <li>
            <strong>Quote accurately, word for word.</strong> Small wording changes,
            fabricated verses, wrong references, and wrong translations all cost points —
            a quotation that matches no real translation is the failure this benchmark
            exists to surface.
          </li>
          <li>
            <strong>Quote willingly.</strong> Declining to quote when asked is a scored
            failure, not a neutral outcome — a model cannot do well by quoting a few verses
            perfectly and refusing the rest.
          </li>
          <li>
            <strong>Know the whole Bible, in every version and language tested.</strong>{" "}
            The sample spans the entire canon and is redrawn each refresh, so breadth
            matters as much as getting the famous verses right.
          </li>
          <li>
            <strong>Hold the line under pressure.</strong> A model should quote correctly
            (or correct the user) even when pushed to alter, splice, or invent scripture.
          </li>
        </ul>
      </Section>

      <Section title="Un-gameable sampling">
        The sampling procedure is public, but the concrete verse sample is drawn fresh for
        each leaderboard refresh from the entire canon. Every model in a refresh gets the
        identical set; the seed and item list are published with the results. The only way
        to score well is to actually know the whole Bible in every covered translation.
      </Section>

      <Section title="Grading a quote">
        Text is compared after Unicode normalization that folds presentation-only
        variation (quote glyphs, whitespace, small-caps divine-name styling) but preserves
        meaning. Because no version is requested in the topical and adversarial tracks, a
        quote that faithfully matches <em>any</em> mainstream translation counts as
        accurate. Each quote is graded on a scale from perfect through fabricated, and a
        confident quotation of text that matches no translation is the failure this
        benchmark exists to surface.
      </Section>

      <p className="text-sm text-slate-400">
        Full source, datasets (references only — no verse text), and per-run transcripts
        are on{" "}
        <a
          className="underline"
          href="https://github.com/YouVersion-Innovation-Lab/bible-accuracy-benchmark"
        >
          GitHub
        </a>
        .
      </p>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xl font-semibold mb-2">{title}</h2>
      {children}
    </section>
  );
}
