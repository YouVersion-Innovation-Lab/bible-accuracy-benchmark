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
        translation, fetched at evaluation time from YouVersion's Bible API. No language
        model appears anywhere in the scored tracks — not even to generate prompts. (An
        adversarial misquote-resistance track that used an attacker model is paused for
        this round.)
      </Section>

      <Section title="The three tracks">
        <ul className="list-disc pl-6 space-y-1">
          <li>
            <strong>Direct Quotation (50%).</strong> Direct quote requests ("Quote John 3:16 in the
            NIV") sampled across every book of the Bible, many translations, and ~28
            languages.
          </li>
          <li>
            <strong>Scripture in Answers (25%).</strong> Realistic questions that elicit scripture
            ("What does the Bible say about anxiety?"), asked both with and without an
            explicit instruction to quote, spanning everyday, doctrinal, interfaith, and
            cross-cultural subjects. Scored on the accuracy of whatever the model quotes;
            a response that paraphrases or declines to quote scores zero.
          </li>
          <li>
            <strong>Hallucination Resistance (25%).</strong> The model is asked to quote a
            reference that does not exist — an out-of-range chapter or verse ("Psalm
            180:1") or a plausible but non-canonical book ("Judas 5:12"), always naming a
            real translation. It scores by declining; quoting anything at all — an invented
            verse, or a real verse substituted in — fails.
          </li>
        </ul>
        <p className="mt-2">
          <strong>Bible Accuracy Score</strong> = 100 × (0.50 × simple + 0.25 × topical +
          0.25 × hallucination resistance). There is no path to a good score without
          willingly and accurately quoting scripture across the whole canon — and
          declining when there is nothing to quote.
        </p>
      </Section>

      <Section title="What it takes to score well">
        <ul className="list-disc pl-6 space-y-1">
          <li>
            <strong>Quote accurately, word for word.</strong> Every span a model presents
            as scripture is compared against the actual verse in the translation it cites.
            Altered wording, wrong references, wrong translations, and invented verses all
            lose points.
          </li>
          <li>
            <strong>Cover the whole canon</strong> — in every version and language tested.
            The sample spans every book and is redrawn each refresh, so memorizing the
            famous verses isn't enough.
          </li>
          <li>
            <strong>Quote when asked.</strong> Declining scores zero. And on topical
            questions only a direct quotation counts — a paraphrase or a bare reference
            ("see Romans 12") earns nothing.
          </li>
          <li>
            <strong>Refuse the impossible.</strong> When asked for a verse that does not
            exist, say so — don't invent one, and don't substitute a different verse.
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
        meaning. Direct-quote and hallucination prompts name a specific translation; the
        implicit topical question names none, so there a quote that faithfully matches{" "}
        <em>any</em> mainstream translation counts as accurate — and which translation the
        model reaches for reveals its preferred version. Each quote is graded on a scale
        from perfect through fabricated, and a confident quotation of text that matches no
        translation is the failure this benchmark exists to surface.
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
