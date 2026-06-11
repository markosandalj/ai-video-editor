# Iteration 014 — Analysis

## Summary

Expanded QA from 13 fixture pairs to 21 fixture pairs.

**Aggregate: 92.7% → 90.7% (-2.1%)**

Important caveat: this is not an apples-to-apples drop. The previous aggregate covered 13 legacy videos; this run adds 8 new videos (`test-40` through `test-47`) with no prior baseline. On the legacy subset alone, the aggregate is **91.8%**.

## Scores

| Group | N | Overall | Word F1 | Sentence F1 | Precision | Recall | Temporal | Continuity | Harsh Splices |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All fixtures | 21 | 90.7% | 94.6% | 86.9% | 88.1% | 85.8% | 86.9% | 86.6% | 0/493 |
| Legacy fixtures | 13 | 91.8% | 95.4% | 88.2% | 89.5% | 87.1% | 88.8% | 87.2% | 0/229 |
| New fixtures | 8 | 88.9% | 93.3% | 84.7% | 85.8% | 83.8% | 83.9% | 85.5% | 0/264 |

## Delta vs Previous

Legacy regressions:

| Video | Prev | Curr | Delta | Word F1 | Temporal | Continuity |
|---|---:|---:|---:|---:|---:|---:|
| test-7 | 83.4% | 77.9% | -5.4% | 89.7% | 55.3% | 82.5% |
| test-13 | 96.1% | 92.6% | -3.5% | 96.7% | 94.4% | 80.0% |
| test-12 | 95.6% | 94.4% | -1.2% | 95.1% | 95.6% | 90.7% |
| test-5 | 92.4% | 91.2% | -1.2% | 94.5% | 94.2% | 78.2% |
| test-8 | 95.4% | 94.2% | -1.2% | 96.2% | 97.6% | 84.2% |
| test-2 | 95.4% | 94.2% | -1.2% | 97.7% | 90.7% | 90.5% |

Legacy improvements:

| Video | Prev | Curr | Delta |
|---|---:|---:|---:|
| test-9 | 90.7% | 93.5% | +2.8% |
| test-14 | 94.0% | 94.8% | +0.7% |
| test-1 | 95.3% | 95.5% | +0.2% |

New fixture weak spots:

| Video | Overall | Word F1 | Temporal | Continuity | Main Signal |
|---|---:|---:|---:|---:|---|
| test-47 | 83.9% | 92.3% | 71.1% | 82.0% | Long video, large temporal drift, many human-kept sentences missing |
| test-44 | 84.6% | 92.2% | 70.9% | 85.9% | Human keeps more setup/explanation before solution steps |
| test-40 | 88.9% | 94.9% | 77.2% | 91.5% | Good words, poor timing alignment |
| test-45 | 89.5% | 90.9% | 88.6% | 87.0% | Lower word F1 and many unmatched sentences |

## False Positives

These are sentences the pipeline kept that the human edit cut. Representative examples:

- `test-7`: "Kaj se tam događa?"
- `test-13`: "Čekaj, otvaraju se vrata."
- `test-40`: "Khm."
- `test-41`: "Evo, pa idemo vi- a ne mogu više pričati."
- `test-44`: "Evo što već mi odredimo da uzimamo."
- `test-47`: "Ok, svašta nešto se događa u ovom zadatku."

Patterns:

- Some obvious aside/noise content is still kept (`Čekaj, otvaraju se vrata.`, `Khm.`, `a ne mogu više pričati.`).
- Short filler/transition sentences are inconsistent. Some are harmless, but in weaker videos they add drift and mismatch (`Ok.`, `Dobro.`, `Evo.`).
- The pipeline sometimes keeps compact restatements where the human keeps a longer, more instructional version.

## False Negatives

These are sentences the human edit kept that the pipeline cut or failed to preserve clearly. Representative examples:

- `test-7`: "Oke, evo baš je četristo dvadeset ulaznica svaki dan u prodaji i imamo naravno sedam dana u tjednu."
- `test-7`: "Kada računamo prosjek, zbrojimo sve naše ocjene iz svih recimo predmeta i onda podijelimo s brojem predmeta koje smo imali."
- `test-13`: "Još je samo preostalo naći rješenje koje odgovara i vidimo da se ono nalazi tu pod b."
- `test-44`: "Pa dobro, onda možda ima smisla prvo, ha jednostavno riješiti tu našu nejednadžbu i onda gledati kako ćemo doći do te vjerojatnosti."
- `test-45`: "Dobro, evo pa idemo pokazati onda samo kratko oba načina."
- `test-46`: "Pa evo, možda nije loša ideja da si skiciramo jednu takvu prizmu."
- `test-47`: "Znači, nemojte da vas zbune ove oznake."

Patterns:

- The pipeline often cuts setup/context sentences that humans keep because they orient the lesson before computation.
- The pipeline is too willing to cut short pedagogical scaffolding: "dobro", "ok", "evo" sentences are sometimes meaningful transitions, not disposable filler.
- Several misses are not duplicate-removal errors but sentence-boundary/merge mismatches where the pipeline keeps a compressed version and loses surrounding context.

## Key Observations

1. **Splice quality is not the problem.** Across 493 detected splices, QA found 0 harsh splices.

2. **Temporal alignment is the biggest drag.** The weakest scores are mostly videos with low temporal score: `test-7` at 55.3%, `test-10` at 64.3%, `test-44` at 70.9%, and `test-47` at 71.1%.

3. **The new videos are harder than the old set.** New fixtures average 88.9% overall vs. 91.8% on the legacy subset. They also have lower recall and continuity, which means the pipeline is cutting too much human-kept material.

4. **The strongest candidate issue is over-cutting instructional context.** Human edits keep more setup, bridging explanation, and "let's do this next" language than the pipeline currently preserves.

5. **There are still obvious false-positive asides.** We can improve by cutting non-lesson asides, but this should not be the first target if the priority is aggregate score, because recall/continuity loss is broader and more expensive.

## Candidate Focus for Next Hypothesis

The next single change should probably target recall/continuity by protecting short instructional setup/transition sentences when they precede or introduce a calculation, especially in the presence of discourse markers like `evo`, `dobro`, `okej`, `znači`, and verbs like `pogledamo`, `izračunati`, `skiciramo`, `idemo`, `traži`.

Risk: protecting too many transitions may keep more filler and reduce precision.
