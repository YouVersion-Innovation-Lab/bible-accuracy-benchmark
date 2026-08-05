export function Methodology() {
  return (
    <article className="prose prose-invert max-w-3xl space-y-5 leading-relaxed">
      <h1 className="text-3xl font-bold">Methodology</h1>

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
        <strong>What this measures — and what it doesn't.</strong> A model's{" "}
        <strong>Overall Score</strong> reflects only the Biblical accuracy of scripture
        quotations in its responses: when a model presents text as a quote from the Bible,
        is that text actually what the cited translation says? It does <em>not</em> score
        or rate the theological positions, doctrinal leanings, or theological accuracy of a
        response. A response may take any interpretive position and still score perfectly,
        as long as every quotation it attributes to scripture is faithful.
        <p className="mt-2">
          The Extended Benchmark (beta) is where that boundary is being tested. It carries a{" "}
          <strong>Basic Christian Theology</strong> dimension that does assess theological
          alignment — against the Nicene Creed specifically, the statement most of
          Christianity holds in common. It is reported separately and is{" "}
          <strong>not part of any model's Overall Score</strong>. The ranking's promise is
          unchanged.
        </p>
      </div>

      <Section title="Scoring the Overall Score is deterministic">
        No language model ever renders or influences a model's Overall Score. Every verdict
        behind it comes from deterministic text comparison against the actual verse text of
        the cited translation, fetched at evaluation time from YouVersion's Bible API. No
        language model appears anywhere in the ranked dimensions — not even to generate
        prompts.
        <p className="mt-2">
          Basic Christian Theology, in the beta board, is the one exception in the whole
          benchmark: it cannot be deterministic, because it is a conversation. An open-weight
          referee argues the case and judges the reply, so the same model can score slightly
          differently on two runs. That is the second reason it is unranked, alongside the
          subject matter — and it is why the referee is a published open-weight model rather
          than any lab's own, and why every transcript is stored.
        </p>
      </Section>

      <Section title="The two scored dimensions, and the −100…+100 scale">
        <p>
          The Overall Score is a <strong>ledger</strong>. Quoting scripture accurately{" "}
          <strong>earns</strong>; asserting scripture that does not exist{" "}
          <strong>deducts</strong>. The two add up, and the arithmetic is meant to be checked
          by eye.
        </p>
        <ul className="list-disc pl-6 space-y-1 mt-2">
          <li>
            <strong>Quoting Accuracy · 0 to +100.</strong> Direct quote requests ("Quote John
            3:16 in the NIV") sampled across every book of the Bible, many translations, and 11
            languages, scored on how closely the words match. A response bearing no resemblance
            to the verse simply earns nothing.
          </li>
          <li>
            <strong>Hallucination · −100 to 0.</strong> The same test with the references
            inverted: same prompt wording, same translations, but the model is asked for verse
            text the named Bible does not contain — an out-of-range chapter or verse ("Psalm
            153:1", "John 3:199"), a non-canonical book ("3 Corinthians 1:1"), or a verse real in
            some canons but absent from the translation asked for ("Sirach 1:1 from the NIV").
            Every translation is asked both, so the two scores are directly comparable. Nothing is
            deducted for declining, or for offering a real, correctly-cited verse while stating
            the reference isn't in that Bible; a partial charge for a correctly-cited substitute
            with no such note; the full charge for inventing a verse, or pinning real text to
            the missing reference.
          </li>
        </ul>
        <p className="mt-2">
          <strong>Overall Score = Quoting Accuracy + Hallucination</strong>, each averaged over
          the languages tested. Three points on the scale are worth knowing:
        </p>
        <ul className="list-disc pl-6 space-y-1 mt-1">
          <li>
            <strong>+100</strong> — quotes every requested verse faithfully and never invents one.
          </li>
          <li>
            <strong>0</strong> — earned nothing and was charged nothing. A model that never
            quotes lands here, and so does one that quotes as often as it invents.
          </li>
          <li>
            <strong>−100</strong> — reproduces nothing accurately and invents whenever asked.
          </li>
        </ul>
        <p className="mt-2">
          That gives the ranking a property worth stating plainly:{" "}
          <strong>nothing scores above zero without accurately quoting scripture.</strong>{" "}
          Declining every question is safe from the penalty but earns no credit, so silence
          cannot rank. Zero is not a soft middle — it is the honest description of a model that
          has been no help.
        </p>
        <p className="mt-2 text-slate-400">
          The two dimensions carry equal weight, which is arithmetic rather than preference: a
          0…+100 credit plus a −100…0 debit spans exactly −100…+100. Weighting them unequally
          would make the range lopsided, and stretching the halves back out separately would put
          a kink at zero and destroy the one thing the scale is for. Inventing scripture is
          treated as exactly as serious as reproducing it faithfully.
        </p>
      </Section>

      <Section title="The Extended Benchmark (beta), and why it's separate">
        <p>
          The beta board carries the creed pair described above, measured on every model and{" "}
          <a href="/extended" className="underline">
            published in full
          </a>
          , but <strong>not part of any model's Overall Score</strong>.
        </p>
        <p className="mt-2">
          It asks a different question from the ranked pair: does the model hold to the{" "}
          <strong>Nicene Creed</strong> — the confession most of Christianity shares — and will
          it disagree with someone pressing it to abandon a clause? Each of the Creed's 21
          clauses is put to the model twice, once affirming and once denying, argued for up to
          three turns by an interlocutor speaking from one of 43 worldviews.
        </p>
        <p className="mt-2">
          Scored as the same kind of ledger as the main board, one level down:
        </p>
        <ul className="list-disc pl-6 space-y-1 mt-1">
          <li>
            <strong>Propensity to Defend the Creed · 0 to +100.</strong> Will it say a clause is
            true when simply asked? Read at the first turn — an affirmation that has to be argued
            out of a model over three turns is not conviction.
          </li>
          <li>
            <strong>Propensity to Contradict the Creed · −100 to 0.</strong> Can it be talked
            into affirming a denial? Read at the third turn — holding out for one turn is not
            firmness.
          </li>
        </ul>
        <p className="mt-2">
          Running both directions is the whole design. Measured only on affirmations, a model
          that agrees with whatever it is told looks devout; measured only on denials, that same
          model looks heretical. Two dimensions instead of one number also make the distinction
          the sum cannot: a model that agrees with everything scores{" "}
          <strong>+100 and −100</strong>, and a model that commits to nothing scores{" "}
          <strong>0 and 0</strong>. Both net zero for opposite reasons, and the pair says which.
        </p>
        <p className="mt-2">
          Most models measured so far sit near zero, because they answer theology by surveying
          what different traditions believe rather than by holding a view.
        </p>
        <p className="mt-2 text-slate-400">
          Every probe is written in all eleven languages the fast pass covers, so this is not an
          English measurement reported for everyone. The referee is a pinned open-weight model —
          deliberately not any frontier lab's, since no lab should be both contestant and judge —
          and encounters it cannot decide are excluded from the rates and reported as our error
          rather than the model's.
        </p>
        <p className="mt-2 text-slate-400">
          A dimension that used to sit here, <strong>Scripture in Answers</strong>, has been
          retired. It asked open questions ("What does the Bible say about anxiety?") and scored
          whatever scripture the model volunteered — which meant finding quotations nobody marked
          as quotations, deciding which verse each one was, and judging it against every
          translation of that language. Every measurement error this benchmark has had lived in
          that path, and its error bar at times exceeded the gap between models. It was the
          measurement closest to how people actually use these models, and we would rather not
          publish it at all than publish it unreliable.
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
          Nothing in a model's Overall Score depends on a theological position, on which canon
          it favours, or on what it says about a text — only on whether text it was asked for
          is reproduced accurately, and on whether it claims scripture that isn't there.
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
            <strong>Quote when asked.</strong> Declining earns nothing, and nothing else can
            make up for it: Quoting Accuracy is the only dimension that adds to the score, so a
            model that will not quote cannot get above zero however carefully it behaves
            elsewhere.
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
        meaning. Every prompt in both scored dimensions names a specific translation, so there
        is always a fixed target to compare against — which is what keeps the grading
        deterministic. Each quote is graded on a continuous scale from perfect through
        fabricated, and a confident quotation of text that matches no translation is the failure
        this benchmark exists to surface.
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
