# Architecture

nitless does two things. Deterministic code decides what the model sees, and a separate model pass tries to
refute each finding before it is published. A finding has to be justified by this repository, and returning
no findings is a valid result.

```
PR/MR URL ──► acquire (GitHub or GitLab API + shallow git fetch of base and head)
           ──► repository config (.nitless.yml and prompt overrides, read at the base commit)
           ──► re-run plan (previous state in the summary comment: unchanged, incremental or full)
           ──► diff ──► triage (trivial / normal / risky hunks) ──► size budget
           ──► context ┬─ profile      repo map, manifests, docs, lint configs        (deterministic)
                       ├─ related code symbol graph: callers, callees, siblings, tests (deterministic)
                       ├─ intent       task source > story file in repo > PR/MR text   (fast model)
                       └─ conventions  rules with file:line evidence from sibling code (fast model)
           ──► review units ──► reviewer per unit ∥ requirements check                (strong model)
           ──► merge, de-duplicate ──► verifier per finding ──► confidence floor, cap  (verifier model)
           ──► adapters: json | markdown | github | gitlab
```

[nitless/pipeline.py](nitless/pipeline.py) runs these stages in order. Every choice a stage makes is written
to `context_trace` in the result.

## Stages

| Stage        | Module                                                  | What it does                                                                   |
| ------------ | ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Preflight    | `config.py`, `llm/`, `scm/`                             | validates settings, the LLM key and models, and repo access                    |
| Acquire      | `scm/github.py`, `scm/gitlab.py`, `scm/local.py`        | loads the PR or MR metadata and fetches base and head                          |
| Repo config  | `repo_config.py`, `prompts/__init__.py`                 | applies `.nitless.yml` under the environment; team rules go into the prompts   |
| Re-run plan  | `incremental.py`                                        | reuses the signed state of the last review: same head, or only changed files   |
| Triage       | `review/triage.py`                                      | drops trivial hunks and excluded files, marks risky files                      |
| Profile      | `context/profile.py`, `docs.py`, `manifests.py`, `lint.py`, `repo_map.py` | repo map, manifests, lint configs, relevant doc sections  |
| Related code | `context/symbols.py`, `graph.py`, `packer.py`           | finds changed symbols and their neighbours, then packs them into a token budget |
| Intent       | `context/intent.py`                                     | turns the task into intent, acceptance criteria and out-of-scope items         |
| Conventions  | `context/conventions.py`                                | lists the rules sibling code follows, each with a checked citation             |
| Units        | `review/units.py`                                       | splits large diffs along the symbol graph                                      |
| Review       | `review/naive.py`, `review/requirements.py`             | finds issues in each unit; a separate call checks the acceptance criteria      |
| Verify       | `review/verifier.py`, `review/postprocess.py`           | argues against each finding, then applies the confidence floor and the cap     |
| Publish      | `output/`                                               | sends the result to the json, markdown, github and gitlab adapters             |

Prompts are in [nitless/prompts/](nitless/prompts/), one file per call; a repository can replace a system prompt. The result model is in
[nitless/models.py](nitless/models.py).

## Context

All context is chosen by code, not by a model. Each item has a reason and a token count.

- **Profile** (`CONTEXT_BUDGET_TOKENS`). Long docs such as README, CONTRIBUTING, ADRs and AGENTS.md are split
  into sections. A section is kept only if it shares terms with the changed paths.
- **Related code** (`RELATED_BUDGET_TOKENS`). tree-sitter parses Python, JS/TS and Java to find the changed
  symbols. For each one the graph collects:
  - the enclosing definition
  - callers, found with git grep and confirmed by a parse
  - callees
  - sibling files with the same role, e.g. `*Service.java`
  - tests
  
  Snippets are trimmed to the relevant lines, scored by how close they are to the change, and dropped
  lowest score first until they fit the budget.
- **Intent.** The task comes from `TASK_SOURCE`, else a story file the change touches, else the PR or MR
  description. Out-of-scope items go to the verifier so deferred work isn't flagged.
- **Conventions.** A fast model reads 2–4 sibling files per changed area and writes rules, each with a
  `file:line` citation. Rules whose citation doesn't match the file are dropped.

## Review and verification

The reviewer gets the profile, conventions, related code, intent and the annotated diff. Each finding it
returns has a location, severity, category, rationale and evidence. A diff over `UNIT_BUDGET_TOKENS` is split
into units that are reviewed in parallel, each with its own related code. Small changes stay as one unit.
With `TOOLS=on`, the reviewer and verifier also get read-only repo tools.

After review, candidates are merged and de-duplicated. The verifier then checks each one on its own, with the
material it cites. It looks for reasons to drop it: wrong, pre-existing, out of scope, correct in this
project, a nit, or a duplicate. It keeps, drops or downgrades the finding and gives a confidence. Findings
below `MIN_CONFIDENCE` are dropped, at most one test-coverage finding is kept, and `MAX_FINDINGS` caps the
total.

## Failures

Each failure is a typed error in [nitless/errors.py](nitless/errors.py) with its own exit code, plus an
`error` block in the JSON. A failed run never reports findings, and the github and gitlab adapters never
post it. A spent quota fails immediately (exit 7), so a partial review never looks clean. Per-minute rate
limits are waited out. An oversized diff is reviewed risky files first, with `status: partial`.

## Design decisions

Numbers are from [eval/RESULTS.md](eval/RESULTS.md).

1. **Deterministic context instead of a repo dump.** Bugs that only show up in related code are the hardest
   class. Adding the symbol graph raised recall on them from 3/18 to 12/12, for about 4k extra tokens per review.
2. **A separate verifier instead of a "be careful" prompt.** Asking the reviewer to be strict lowers recall.
   A second pass can be strict on its own: it raised precision from 0.66 to 0.88 and lost no true findings.
3. **The requirements check is its own call.** A change can pass review and still not do what was asked.
   Keeping it separate keeps the criteria list complete and lets its result feed the verifier.
4. **Units only for large diffs.** Splitting bounds the size of each call. Small changes keep the exact
   single-call prompt, because splitting them didn't help.
5. **Model-agnostic, calibrated on Opus.** Any model with tool calling works. Opus 5.5 did best in the
   reviewer comparison, and the 0.6 confidence floor was tuned on its verifier. Models from other families
   rate almost everything they keep above 0.7, so verifying with a different family was not adopted.
