# LongMemEval Failure Analysis — RecallVault Phase 1 & 2

Tracks miss counts across all three completed benchmark runs. Concrete examples
are from the baseline run; Phase 2a/2b counts show whether each pattern was resolved.

| Run | Config | Total misses |
|---|---|---|
| Baseline | MiniLM-L6-v2, per-turn | 40 |
| Phase 2a | MiniLM-L6-v2, window=3 overlap=1 | 38 |
| Phase 2b | BGE-large-en-v1.5, window=3 overlap=1 | 19 |

Results files:
- `results/run_20260420T230752.jsonl` (baseline)
- `results/run_20260421T173740_w3o1.jsonl` (Phase 2a)
- `results/run_20260421T233611_w3o1_bgelarge.jsonl` (Phase 2b)

---

## Miss count by category across all runs

| Category | n | Baseline | Phase 2a | Phase 2b |
|---|---|---|---|---|
| temporal-reasoning | 133 | 15 | 12 | **7** |
| multi-session | 133 | 10 | 12 | **2** |
| single-session-user | 70 | 8 | 6 | **3** |
| single-session-preference | 30 | 4 | 6 | **4** |
| knowledge-update | 78 | 2 | 2 | **1** |
| single-session-assistant | 56 | 1 | 0 | 2 |

---

## Pattern 1 — Temporal distance framing

**Category:** temporal-reasoning | **Misses: baseline 15 → Phase 2a 12 → Phase 2b 7**

**What happens:** The question asks "how many days/weeks/months ago did X happen?"
or "how many days between event A and event B?". The gold session describes the
*event* itself in its own conversational context. The query's temporal framing
("how many days ago", "how many weeks") produces an embedding that does not
resemble the event-centric content of the gold session.

**Phase 2a:** 3 misses resolved by sliding-window context. When a dated event is
mentioned in a user turn immediately followed by an assistant acknowledgment, the
3-turn window provides enough surrounding context for the event embedding to shift
closer to the temporal query. 3 new misses appeared elsewhere (window occasionally
mixed temporally-adjacent but topically-unrelated turns).

**Phase 2b:** 5 additional misses resolved. BGE-large's stronger cross-sentence
semantic understanding better bridges the temporal-framing vs. event-content gap.
7 misses remain — these are questions where the event session's dominant topic is
entirely unrelated to the dated event mentioned incidentally.

**Status: Partially resolved.** 7 remaining misses are structural: the event
mention is incidental in a session about something else, and no embedding model
alone will surface it reliably without date-indexed retrieval.

**Examples (baseline misses):**

```
qid: gpt4_468eb063
Q:   "How many days ago did I meet Emma?"
gold: answer_9b09d95b_1
gold_content: "I just attended a digital marketing workshop and networking event…"
retrieved: e60a93ff_2  (not gold)
```

```
qid: gpt4_4ef30696
Q:   "How many days passed between the day I finished reading 'The Nightingale'
     and the day I started reading 'The Hitchhiker's Guide to the Galaxy'?"
gold: answer_f964cea3_1, answer_f964cea3_2
retrieved: 4067bede, 80b3f093  (neither is gold)
```

**Future fix:** Embed a `[DATE: YYYY-MM-DD]` prefix into each chunk at ingest time
so the date string becomes part of the vector. This would let "how many days ago"
queries find date-proximate chunks regardless of topic mismatch.

---

## Pattern 2 — Multi-session aggregation with semantic mismatch

**Category:** multi-session | **Misses: baseline 10 → Phase 2a 12 → Phase 2b 2**

**What happens:** The question is a counting question spanning multiple sessions
("how many projects have I led?", "how many magazine subscriptions do I have?").
There are 3–4 gold sessions, each contributing one item to the count. The query
embeds as a meta-question about the aggregate, not matching any individual session.

**Phase 2a:** Slight regression (+2 misses). Windowing occasionally merged a
gold-session turn with surrounding unrelated turns, diluting the signal enough
to drop it below the top-5 cutoff.

**Phase 2b: 8 misses resolved — the biggest architectural win of Phase 2.** BGE-large's
superior understanding of entity and concept relationships bridges the semantic gap
between "how many X do I have?" and "I acquired another X…". Only 2 misses remain,
likely questions where the gold sessions' content is genuinely underspecified.

**Status: Largely resolved by BGE-large.** The 92.5% → 98.5% jump in multi-session
is the dominant result of Phase 2b.

**Examples (baseline misses):**

```
qid: 6d550036
Q:   "How many projects have I led or am currently leading?"
gold: answer_ec904b3c_1, _2, _3, _4  (4 gold sessions)
gold_content: "I'm working on a project that involves analyzing customer data…"
retrieved: 2e4430d8_2, sharegpt_zciCXP1_12  (neither is gold)
```

```
qid: e3038f8c
Q:   "How many rare items do I have in total?"
gold: answer_b6018747_1, _2, _3, _4
retrieved: a3d8e134_2  (not gold)
```

---

## Pattern 3 — Incidental fact mention in off-topic session

**Category:** single-session-user (primary) | **Misses: baseline 8 → Phase 2a 6 → Phase 2b 3**

**What happens:** A specific fact (degree, previous occupation, discount amount) was
mentioned as a passing detail in a session whose main topic was something entirely
different. The session embedding is dominated by the main topic; a query targeting
the incidental fact doesn't match the session well despite the fact being literally
present in the text.

**Phase 2a:** 2 misses resolved. Slightly wider context sometimes helps, especially
when the fact appears in one turn and is echoed or elaborated by the assistant in
the next turn (both now in the same window).

**Phase 2b:** 3 additional misses resolved (5 total vs. baseline). BGE-large
handles multi-topic documents better than MiniLM, giving more weight to the
incidental fact even when the session's dominant topic is different.

**Status: Significantly improved but not eliminated.** 3 remaining misses are
questions where the fact was mentioned in a single short turn with no echo, inside
a session that is semantically far from the query.

**Examples (baseline misses):**

```
qid: e47becba
Q:   "What degree did I graduate with?"
gold: answer_280352e9
gold_content: "I'm trying to organize my life a bit better, can you recommend
  some task management apps? / Congratulations [on your Business Administration
  degree]…"  — degree is a one-clause aside in a task-management session
retrieved: sharegpt_QZMeA7V_17, f6859b48_2  (neither is gold)
```

```
qid: 5d3d2817
Q:   "What was my previous occupation?"
gold: answer_235eb6fb
gold_content: "I'm trying to get more organized with my new role / Congratulations
  on your new role! Getting organized…"
retrieved: sharegpt_BKl952A_23, sharegpt_ipLglky_48  (neither is gold)
```

**Future fix:** Sliding-window chunking with a wider window (5–7 turns) would
keep the incidental fact in context with more surrounding content. Alternatively,
entity extraction at ingest time would handle these via the verified fact store
rather than relying on vector retrieval.

---

## Pattern 4 — Implicit preference retrieval (structural limitation)

**Category:** single-session-preference | **Misses: baseline 4 → Phase 2a 6 → Phase 2b 4**

**What happens:** The user expressed a preference or habit in one session (e.g.,
experimenting with turbinado sugar in baking), but the retrieval query reformulates
the need implicitly ("my chocolate chip cookies need something extra"). The semantic
distance between the original preference statement and the reformulated query is too
large for embedding-only retrieval to bridge.

**Phase 2a:** 2 new misses appeared (regression). Windowing occasionally diluted
preference signals by merging preference-expressing turns with surrounding off-topic
turns, weakening the embedding.

**Phase 2b: Recovered to baseline (4 misses) — but did NOT improve beyond it.**
BGE-large corrected the windowing regression but added no additional hits. The
miss count is identical to the baseline despite a far stronger embedder.

**This is the key structural finding of Phase 2:** single-session-preference is
the only category that did not improve end-to-end. The miss rate is the same at
86.7% in both baseline and Phase 2b. This is not an embedding-quality problem —
it is a query-reformulation problem. The user's stored preference ("I've been
experimenting with turbinado sugar") and the retrieval query ("my cookies need
something extra") are semantically distant in any embedding space because they
describe the same underlying preference from completely different angles. No
embedding model trained on general text will reliably bridge this gap without
explicit query rewriting.

**Future fix (Phase 3):** HyDE (Hypothetical Document Embeddings) or LLM-based
query expansion before embedding — generate a hypothetical memory entry that the
question is *likely asking about*, embed that, and use it as the retrieval query.
This is an LLM-layer intervention, not an embedding upgrade.

**Examples (baseline misses, all still failing in Phase 2b):**

```
qid: 38146c39
Q:   "I've been feeling like my chocolate chip cookies need something extra. Any advice?"
gold: answer_772472c8
gold_content: "I've been experimenting with different types of sugar and found
  that turbinado sugar adds a nice crunch / Turbinado sugar is a great choice!
  Its partially refined state and subtle caramel notes…"
note: "cookies need something extra" ↔ "turbinado sugar experiment" — no
      embedding model trained on general text bridges this reliably.
```

```
qid: 09d032c9
Q:   "I've been having trouble with the battery life on my phone lately. Any tips?"
gold: answer_b10dce5e
gold_content: "I'm looking for some advice on the best way to organize my tech
  accessories, like cables, chargers… / The eternal struggle of keeping tech
  accessories organized while traveling…"
note: Battery life → tech accessories. Preference expressed in a different
      frame from the query.
```

---

## Pattern 5 — Multi-gold knowledge-update with both sessions missed

**Category:** knowledge-update | **Misses: baseline 2 → Phase 2a 2 → Phase 2b 1**

**What happens:** A knowledge-update question has two gold sessions (the original
statement and the update). R@5 only requires one to appear in the top 5, but
neither does. The retrieved chunk is from a third, unrelated session.

**Phase 2a:** No change (2 misses). Windowing does not help when the session's
main topic is not the fact being updated.

**Phase 2b:** 1 miss resolved. BGE-large surfaces one of the two gold sessions
for the remaining question.

**Status: Mostly resolved.** 1 miss remains. Notably, this pattern is where
the verified fact store (already implemented in RecallVault's production pipeline)
would have handled these questions via structured key-value lookup rather than
vector retrieval — if fact extraction had captured the specific values being asked
about (page count, wake-up time). This is a fact-extraction coverage issue, not
a retrieval issue.

**Examples (baseline misses):**

```
qid: 184da446
Q:   "How many pages of 'A Short History of Nearly Everything' have I read so far?"
gold: answer_e2f4f947_1, answer_e2f4f947_2
retrieved: bf633415_2  (not gold)
note: Page count update across two sessions. If fact extraction had captured
      "pages_read=X" for this book, the verified path would answer correctly.
```

---

## Summary: what Phase 2 resolved and what remains structural

| Pattern | Baseline misses | Phase 2b misses | Resolved? |
|---|---|---|---|
| Temporal distance framing | 15 | 7 | Partially — date indexing needed for remainder |
| Multi-session aggregation | 10 | 2 | Largely resolved by BGE-large |
| Incidental fact in off-topic session | 8 | 3 | Improved — wider windows would help further |
| Implicit preference retrieval | 4 | 4 | **Structural — query rewriting needed, not embedding** |
| Multi-gold knowledge-update | 2 | 1 | Largely resolved |

The single-session-preference pattern is the clearest signal for Phase 3 design:
it requires HyDE or LLM-based query expansion, and any benchmark specifically
targeting this category should verify that the evaluation infrastructure measures
the full retrieval + rewriting pipeline, not just the embedding step.
