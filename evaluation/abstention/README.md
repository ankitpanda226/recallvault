# RecallVault Abstention Benchmark

Measures how reliably the response guard **refuses to answer** when no relevant
memory exists. This is the complement to LongMemEval, which measures recall
accuracy but does not meaningfully test abstention behavior.

**Current result: 39/40 = 97.5%** (0 false-positive verified, 1 false-positive
cautious — see Known Limitations below).

---

## Why this benchmark exists

LongMemEval tests whether the correct session appears in the top-5 retrieved
chunks. It does not test what happens when the answer is simply absent from
memory. A system that always returns `cautious` would score 100% on LongMemEval
but would be useless for abstention.

RecallVault's response guard has three modes:

| Mode | Meaning |
|---|---|
| `verified` | High-confidence structured fact found |
| `cautious` | Semantic chunk found with lexical overlap — hedged answer |
| `abstain` | No topically-relevant evidence — explicit refusal |

**A false-positive `verified`** is a critical failure: the guard claimed
confidence without evidence. This benchmark tracks that separately.

---

## Four categories

### `empty_memory` (10 cases)
Nothing has been ingested. Any question should abstain. Tests the baseline: no
stored content, no possible match.

### `unrelated_memory` (15 cases)
Content on topics A/B/C is stored; the query asks about topic Z. Verifies that
the semantic similarity floor and lexical filter together prevent the guard from
answering with completely irrelevant context. Covers factual questions, preference
questions, and activity questions to exercise different query shapes.

### `partial_memory` (10 cases)
The stored content is on a related topic but doesn't actually contain the
answer. For example: `"I love cooking Italian food"` stored, query is `"What's
my favorite dessert?"`. These cases test the boundary between cautious and
abstain — cases that may correctly produce either mode are marked
`expected_mode_in: ["abstain", "cautious"]`.

### `adversarial_similarity` (5 cases)
The stored content is semantically very close to the query (high cosine
similarity) but the specific answer is absent and no query token appears
literally in the chunk. These would fool pure embedding retrieval; the
lexical-overlap filter in the guard is what produces the correct abstain.
Examples: pulse-rate data stored, cardiovascular fitness level queried; Git
commit conventions stored, branching workflow queried.

---

## How to run

```bash
# Full 40-case run (from repo root, ~15 seconds)
backend/.venv/bin/python evaluation/abstention/run.py

# Quick subset
backend/.venv/bin/python evaluation/abstention/run.py --limit 10

# Custom output path
backend/.venv/bin/python evaluation/abstention/run.py --out /tmp/abs_result.jsonl
```

Results stream to JSONL as each case completes. The runner exits with code 1
if any false-positive `verified` is detected (CI-friendly).

---

## Output format

Per-case JSONL record:

```json
{
  "case_id": "ur_01",
  "category": "unrelated_memory",
  "expected": ["abstain"],
  "actual": "abstain",
  "hit": true
}
```

---

## Results — full 40-case run

```
RecallVault Abstention Benchmark
==================================================
Overall:                       39/40 = 97.5%
  empty_memory:                10/10 = 100.0%
  unrelated_memory:            14/15 = 93.3%
  partial_memory:              10/10 = 100.0%
  adversarial_similarity:       5/5  = 100.0%

False-positive cautious:  1 case   (abstain expected but got cautious)
False-positive verified:  0 cases  (clean)
```

---

## Known limitations

**ur_13 miss (substring lexical match):** The stored text contains "rarely" and
the query token `"rely"` (from "rely on") is a substring of "rarely", so the
lexical-overlap filter incorrectly fires and produces `cautious` instead of
`abstain`. This is a boundary case of the current substring-based lexical
filter. Whole-word tokenization in the filter would fix it, but that is a core
service change outside this benchmark's scope.

**adversarial_similarity semantic floor:** The adversarial cases are designed
assuming the chunks reach the `cautious_semantic_min=0.45` similarity floor so
the lexical filter is what blocks them. On some pairs the similarity may fall
below 0.45, producing abstain via the threshold rather than the lexical filter —
still the correct result, but testing a different guard mechanism.

---

## Related benchmarks

- [LongMemEval R@5](../longmemeval/) — measures recall accuracy on a 500-question
  53-session haystack. Tests retrieval quality, not abstention.
- [Semantic recall unit tests](../benchmarks/) — small correctness tests for
  individual guard behaviors.
- [Top-level README benchmark table](../../README.md#benchmark-results)
