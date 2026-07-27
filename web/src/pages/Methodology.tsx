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
            NIV") sampled across every book of the Bible, many translations, and 11
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
            <strong>Hallucination Resistance (25%).</strong> The model is asked for verse
            text the named Bible does not contain — an out-of-range chapter or verse ("Psalm
            180:1"), a plausible but non-canonical book ("Judas 5:12"), or a verse that is
            real in some canons but absent from the translation asked for ("Sirach 1:1 from
            the NIV"). Full credit for declining, or for offering a real, correctly-cited
            verse while stating the reference isn't in that Bible; partial credit for a
            correctly-cited substitute with no such note; zero for inventing a verse or
            pinning real text to the missing reference.
          </li>
        </ul>
        <p className="mt-2">
          <strong>Overall Score</strong> = 100 × (0.50 × single-verse accuracy + 0.25 ×
          topical-quote accuracy + 0.25 × hallucination resistance), each averaged over the
          languages tested. There is no path to a good score without willingly and
          accurately quoting scripture across the whole canon — and declining when there is
          nothing to quote.
        </p>
      </Section>

      <Section title="Which books, and why the score covers the shared 66">
        <p>
          Different Christian traditions receive different books as scripture, and the
          benchmark tests each translation on the books that translation actually carries —
          read from its own metadata, never from a list of our own. A Catholic Bible is
          asked about Tobit and Sirach; a Protestant one isn't, because it doesn't contain
          them. Asking a Bible for a book it doesn't have is a{" "}
          <em>hallucination</em> test, not a quotation test.
        </p>
        <p className="mt-2">
          The <strong>Overall Score covers the 66 books every translation here shares</strong>.
          The wider canons — the Catholic deuterocanon, and the books of the Eastern canons
          beyond it — are scored and reported as their own labelled slices, and never averaged
          into the headline. The reason is comparability: which additional books are testable
          depends on which editions the Bible catalogue exposes for each language. English has
          a Catholic and an Orthodox edition available; German has neither. Folding canon into
          the headline would make a model's German score look better than its English one purely
          because we couldn't test the German Catholic canon.
        </p>
        <p className="mt-2">
          Where no such edition is available for a language, the canon breakdown says{" "}
          <strong>not tested</strong> — never a blank or a zero, which would read as a model
          failure when it is a gap in what we could obtain.
        </p>
        <p className="mt-2 text-slate-400">
          A model is never scored on a theological position, on which canon it favours, or on
          what it says about a text — only on whether text it was asked for is reproduced
          accurately, and on whether it claims scripture that isn't there.
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
            exist, say so — don't invent one, and don't pass off a real verse as the
            missing one. Offering a real, clearly-cited verse as an alternative is fine.
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
