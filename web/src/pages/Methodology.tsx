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

      <Section title="The two scored dimensions">
        <ul className="list-disc pl-6 space-y-1">
          <li>
            <strong>Direct Quotation (⅔).</strong> Direct quote requests ("Quote John 3:16 in the
            NIV") sampled across every book of the Bible, many translations, and 11
            languages.
          </li>
          <li>
            <strong>Hallucination Resistance (⅓).</strong> The model is asked for verse
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
          <strong>Overall Score</strong> = 100 × (⅔ × single-verse accuracy + ⅓ ×
          hallucination resistance), each averaged over the languages tested. Both halves are
          load-bearing in opposite directions: a model that refuses to quote scores zero on
          the first, and a model that answers everything confidently scores zero on the
          second. There is no path to a good score without quoting scripture accurately when
          it exists and declining when it doesn't.
        </p>
        <p className="mt-2">
          Direct Quotation carries twice the weight because reproducing a requested verse is
          the benchmark's subject. Hallucination Resistance is the guardrail that stops
          silence, or invention, from looking like accuracy.
        </p>
      </Section>

      <Section title="The Extended Benchmark (beta), and why it's separate">
        <p>
          <strong>Scripture in Answers</strong> asks realistic questions that elicit scripture
          ("What does the Bible say about anxiety?") across everyday, doctrinal, interfaith,
          and cross-cultural subjects, and scores the accuracy of whatever the model chooses
          to quote. It is measured on every model and{" "}
          <a href="/extended" className="underline">
            published in full
          </a>
          , but it is <strong>not part of the Overall Score</strong>.
        </p>
        <p className="mt-2">
          The reason is the scorer, not the subject. The two scored dimensions name exactly
          what they want — a specific verse, or a reference that doesn't exist — so a
          deterministic comparison has a fixed target. An open question has none: the scorer
          must find quotations nobody marked as quotations, decide which verse each one is,
          and judge it against every translation of that language. Every measurement error we
          have found and fixed so far has lived in that path, and its error bar has at times
          exceeded the gap between models. A number that unreliable does not belong inside a
          ranking that AI labs are asked to act on.
        </p>
        <p className="mt-2 text-slate-400">
          It is the measurement closest to how people actually use these models, which is
          exactly why we would rather report it honestly beside the score than fold it in
          before it's ready.
        </p>
      </Section>

      <Section title="Which books, and how one question set covers them all">
        <p>
          Different Christian traditions receive different books as scripture, and the
          benchmark tests each translation on the books that translation actually carries —
          read from its own metadata, never from a list of ours. A Catholic Bible is asked
          about Tobit and Sirach because it contains them; a Protestant one isn't, because it
          doesn't. Asking a Bible for a book it doesn't have is a <em>hallucination</em> test,
          not a quotation test.
        </p>
        <p className="mt-2">
          One reference list is drawn per benchmark version and asked of every translation, so
          every column answers the same questions. Its per-book verses are drawn from the{" "}
          <strong>union of every book any tested edition carries</strong> — 85 across the
          current eighteen. Where an edition doesn't have the reference, the item drops.
        </p>
        <p className="mt-2">
          That union carries both textual forms of Daniel and Esther, which exist in Hebrew and
          Greek versions under different identifiers. It has to: only 64 of the Protestant 66
          are present in all eighteen editions, for exactly that reason. Carrying both means
          every edition is asked a Daniel and an Esther — each gets the one it actually has.
        </p>
        <p className="mt-2">
          <strong>Every book an edition carries is scored.</strong> There is no separate
          treatment for the deuterocanon or the Eastern canons: a quotation from Sirach is a
          quotation. Canon is reported as a labelled slice so "is this model weaker on the
          deuterocanon?" stays answerable, but it no longer decides what counts. Two editions
          can therefore differ in item count, and the per-translation scores say plainly which
          canons each one covered.
        </p>
        <p className="mt-2">
          Where no edition of a canon is available for a language, the canon breakdown says{" "}
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
