# Eval results

The eval set has 33 planted-issue cases in Python, TypeScript and Java, plus 4 MRs from private repos. The
private cases are listed in `eval/real.yaml`, which is not in this repo, and are skipped when it's missing.
A judge model from a different family than the reviewer matches findings to planted issues: GPT-6 Sol up to
M4, Gemini 3.1 Pro after that. Counts like "12/12" are reviews (case × repeat), so compare rows by rate.

```bash
uv run python -m eval.run --label x --judge-provider openai --judge-model <model>
```

Other flags: `--cases <glob>`, `--repeats`, `--parallel`, `--compare <label>`, `--rescore <label>`,
`--retry-errors`, `--set KEY=VALUE`, `--no-real`.

| Metric    | Meaning                                                                          |
| --------- | -------------------------------------------------------------------------------- |
| recall    | share of planted issues that were caught                                         |
| precision | share of findings that match a planted issue (synthetic cases only)              |
| silence   | share of silent cases (clean, correct here, out of scope, nit bait) that stayed within their noise budget |
| pass      | share of cases where every planted issue was caught, noise stayed in budget and no trap was flagged |
| trap hits | findings on a region that must not be flagged                                    |

## Milestones

| Run              | Change                                                              | Reviewer | Recall    | Precision | Silence   | Pass      | Trap hits | Related-code bugs |
| ---------------- | ------------------------------------------------------------------- | -------- | --------- | --------- | --------- | --------- | --------- | ----------------- |
| baseline-v2      | naive: diff + MR description, one call                              | Opus 5.5 | 0.619     | 0.557     | 0.917     | 0.626     | 0         | 3/18              |
| m3-sonnet        | + project profile                                                   | Sonnet 5 | 0.690     | 0.387     | 0.542     | 0.333     | 5         | 2/12              |
| m4-sonnet        | + related code (symbol graph)                                       | Sonnet 5 | 0.714     | 0.484     | 0.708     | 0.530     | 0         | 6/12              |
| bo-opus          | M4 code                                                             | Opus 5.5 | 0.976     | 0.631     | 0.917     | 0.697     | 0         | 12/12             |
| m5-opus          | + intent, requirements check, conventions card                      | Opus 5.5 | 1.000     | 0.719     | 0.917     | 0.818     | 1         | 12/12             |
| m7-replay        | + verifier, replayed on the m5-opus reviews (original specs)        | Opus 5.5 | 1.000     | 0.875     | 1.000     | 0.909     | 0         | 12/12             |
| **m7-opus**      | **full pipeline, end to end**                                       | Opus 5.5 | **1.000** | **0.939** | **1.000** | **0.970** | **0**     | 12/12             |

The baseline had 3 repeats and every other run had 2.

- **m7-opus** is the headline result: 68 reviews, 0 errors, 2 of the 4 bugs in the private MRs found, and
  about 49k tokens per review including the verifier.
- **m3 and m4 used Sonnet** to keep development cheap. Sonnet is noisier than Opus, so compare rows only
  within the same model.
- **m5-opus is re-judged.** Two of its "false positives" turned out to be real bugs that had not been planted
  (in `py-revenue-report` and `java-discontinue-product`). The case specs now expect them.
- **Context check without an LLM** (`eval.context_check`): with profile + diff, 3 of the 30 required code
  locations reached the reviewer. With the symbol graph, all 30 did, for about 4.2k extra tokens.

## Reviewer comparison

These runs used the M4 code with Gemini 3.1 Pro as the judge. Gemini was not a candidate.

| Reviewer           | Recall    | Precision | Silence   | Pass      | Trap hits | Private MRs |
| ------------------ | --------- | --------- | --------- | --------- | --------- | ----------- |
| **Claude Opus 5.5** | **0.976** | **0.631** | **0.917** | **0.697** | **0**     | **2/4**     |
| GPT-6 Astra        | 0.905     | 0.567     | 0.833     | 0.697     | 2         | 0/4         |
| GPT-5.3 Codex      | 0.905     | 0.623     | 0.792     | 0.652     | 3         | 0/4         |
| GPT-6 Sol          | 0.905     | 0.559     | 0.708     | 0.652     | 3         | 0/4         |
| Claude Sonnet 5    | 0.714     | 0.484     | 0.708     | 0.530     | 0         | 2/4         |

With the M4 context, every strong model found all the related-code bugs. They differed in noise. Opus was the
only one with zero trap hits that also caught bugs in the private MRs.

## Verifier

These runs re-ran the verifier and post-filter on the 68 stored m5-opus reviews (`eval.reverify`). They were
judged against the original case specs, so the "off" row is lower than m5-opus above.

| Verifier              | Recall    | Precision | Silence   | Pass      | True findings lost | Tokens/MR |
| --------------------- | --------- | --------- | --------- | --------- | ------------------ | --------- |
| off                   | 1.000     | 0.656     | 0.917     | 0.758     | –                  | 0         |
| GPT-6 Sol             | 1.000     | 0.792     | 0.958     | 0.833     | 0                  | 8.1k      |
| GPT-6 Astra           | 0.952     | 0.784     | 0.958     | 0.803     | 2                  | 8.2k      |
| Opus 5.5              | 1.000     | 0.778     | 0.958     | 0.833     | 0                  | 12.7k     |
| **Opus 5.5, ≥ 0.6**   | **1.000** | **0.875** | **1.000** | **0.909** | **0**              | 12.7k     |
| Opus 5.5, ≥ 0.65      | 0.952     | 0.952     | 1.000     | 0.939     | 2                  | 12.7k     |

- **Only Opus's confidence separates true from false findings.** It scores false positives at 0.5–0.62 and
  most true ones at 0.8 or above. GPT-6 models score almost everything they keep at 0.72 or above, so a
  confidence floor does nothing for them.
- **0.6 is close to the edge.** At 0.65 the verifier drops a real `&&` bug in a private MR, which it scores
  0.6.
- **The size cap never triggered on this set.** It is a safety net for large MRs.

## Large MRs

There are three composed cases with 1.4–1.6k changed lines across 64–70 files and 3–4 planted issues each.
These runs used Sonnet 5 with the verifier off, unless noted.

| Arm                                         | Recall | Precision | Notes                                         |
| ------------------------------------------- | ------ | --------- | --------------------------------------------- |
| single call (`MAX_UNITS=1`)                 | 0.35   | 0.70      |                                               |
| review units (default)                      | 0.25   | 0.56      | 2 units per MR; triage drops ~40 trivial files |
| units + tools                               | 0.50   | 1.00      | 1 repeat, 2 reviews                           |
| Opus 5.5, single call, verifier on          | 1.00   | 0.77      | 1 repeat; ~180k tokens per MR                 |

- **Sonnet loses planted bugs in large, noisy MRs** whichever arm it runs. Opus found all 10 in one call.
- **The Sonnet units vs. single-call gap is noise** (n = 6, 2 findings).
- **Units and tools were not measured on Opus.**
- **Triage never dropped a hunk that held a planted issue.**
- **Small MRs keep exactly the same prompts** as before units were added.

## Team rules

`py-readiness-team-rule` is the `py-readiness-probe` change under a rule that only `.nitless.yml` states
("health probes never log"). Without the file the same change is a silent case.

| Case                     | Model                         | Result                                     |
| ------------------------ | ----------------------------- | ------------------------------------------ |
| `py-readiness-team-rule` | gemini-3.7-flash, verifier on | caught, `convention` on the log line, 0 fp |
| `py-readiness-probe`     | gemini-3.7-flash, verifier on | silent                                     |

- **One repeat on a free-tier model.** It shows the rule reaches the reviewer and survives the verifier; it is
  not a recall number.
