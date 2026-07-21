"""Synthetic multi-script test corpus — the fake book of "1 Testium".

No scripture appears anywhere in the test suite. These invented strings
exercise the same code paths as real verse text: Latin with punctuation,
Cyrillic, Arabic script with vowel points, Persian with ZWNJ, unspaced Thai,
and CJK.
"""

# Latin, long enough that a single-character error stays under the
# near-perfect threshold (QER < 0.005 needs len > 200).
LATIN = (
    "In the seventh season the gardener walked through the orchard rows and "
    "counted every sapling twice, for the ledger of the valley demanded a "
    "faithful record, and no branch, however small, was to be forgotten in "
    "the great accounting of the harvest that was to come."
)

LATIN_NEIGHBOR = (
    "And the keeper of the well drew water at dawn, measuring each jarful "
    "against the mark of the previous year, so that the village might know "
    "whether the springs had kept their promise."
)

# A "different translation" of LATIN: same meaning, distinctly different wording.
LATIN_ALT_VERSION = (
    "During the seventh season, the one who tended the garden passed along "
    "the lines of the orchard and tallied each young tree two times, because "
    "the valley's record book required an honest count, and not one limb, no "
    "matter how little, could be left out of the full reckoning of the coming "
    "harvest."
)

CYRILLIC = (
    "В седьмую пору садовник прошёл по рядам сада и дважды пересчитал каждое "
    "деревце, ибо книга долины требовала верной записи."
)

# Arabic script with harakat (vowel points) — loose mode strips the points.
ARABIC_POINTED = "فِي الفَصْلِ السَّابِعِ سَارَ البُسْتَانِيُّ بَيْنَ الصُّفُوفِ وَعَدَّ كُلَّ غَرْسَةٍ مَرَّتَيْنِ"
ARABIC_PLAIN = "في الفصل السابع سار البستاني بين الصفوف وعد كل غرسة مرتين"

# Persian with ZWNJ (‌) between "می" and the verb stem.
PERSIAN_ZWNJ = "باغبان در فصل هفتم از میان ردیف‌ها می‌گذشت و هر نهال را دو بار می‌شمرد"
PERSIAN_NO_ZWNJ = "باغبان در فصل هفتم از میان ردیفها میگذشت و هر نهال را دو بار میشمرد"

# Thai — no word spacing.
THAI = "ในฤดูที่เจ็ดคนสวนเดินไปตามแถวของสวนและนับต้นกล้าทุกต้นสองครั้งเพราะบัญชีของหุบเขาต้องการบันทึกที่ซื่อสัตย์"

# CJK — no word spacing.
CJK = "第七季，园丁走过果园的行列，把每一株树苗数了两遍，因为山谷的册子要求忠实的记录。"

FAKE_CHAPTER: dict[str, str] = {
    "TST.1.1": LATIN,
    "TST.1.2": LATIN_NEIGHBOR,
    "TST.1.3": "The scribe sealed the ledger with wax and set it in the stone house.",
}
