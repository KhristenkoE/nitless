# nitless

AI code review for GitHub pull requests and GitLab merge requests. It reads the surrounding project (callers,
callees, tests, docs, the task), not just the diff, and a second model pass tries to refute every finding
before it is posted. Most runs produce a few findings, often none.

Works with Anthropic, OpenAI, Gemini, GitHub Models, OpenRouter, Ollama or any OpenAI-compatible server.

## Quick start

### GitHub Action

Add the provider key as a repository secret, then `.github/workflows/review.yml`:

```yaml
name: Review
on:
  pull_request:
permissions:
  contents: read
  pull-requests: write
jobs:
  nitless:
    runs-on: ubuntu-latest
    steps:
      - uses: KhristenkoE/nitless@v0
        with:
          provider: anthropic
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          model: <model>
```

Every pull request gets a review: one comment per finding on its line, plus a summary comment, also shown in
the job summary. Pushing more commits re-runs it; the summary is updated in place and existing findings are not
posted twice. Pull requests from forks get no secrets, so add
`if: github.event.pull_request.head.repo.full_name == github.repository` to skip them.

<details><summary>Action inputs and outputs</summary>

| Input              | Default                    |                                                                         |
| ------------------ | -------------------------- | ----------------------------------------------------------------------- |
| `provider`         | required                   | `anthropic`, `openai`, `gemini`, `github`, `openrouter`, `openai_compat` |
| `api-key`          |                            | the provider key, from a secret                                         |
| `model`            | required                   | review model                                                            |
| `fast-model`       | `model`                    | task extraction and conventions                                         |
| `verifier-model`   | `model`                    | checks every finding                                                    |
| `base-url`         |                            | a proxy or self-hosted endpoint                                         |
| `fail-on`          | `never`                    | fail the step on a finding at or above `critical`, `major` or `minor`   |
| `dry-run`          | `false`                    | write the planned comments to the job summary instead of posting        |
| `env`              |                            | more settings, one `KEY=VALUE` per line (see [Configuration](#configuration)) |
| `github-token`     | `${{ github.token }}`      | reads the pull request and posts the review                             |
| `pull-request-url` | the triggering PR          | review another pull request                                             |

Outputs: `verdict` (`no_issues`, `minor_issues`, `needs_changes`; empty when the run failed), `findings` (the
number published) and `result` (path to the JSON result). A failed run fails the step with the
[exit code](#exit-codes).

</details>

### Docker

You need Docker, an LLM API key, a model name and a GitHub token with pull request write access.

```bash
docker build -t nitless .

docker run --rm \
  -e MR_URL=https://github.com/<owner>/<repo>/pull/<n> \
  -e GITHUB_TOKEN=<token> \
  -e ANTHROPIC_API_KEY=<key> \
  -e MODEL_STRONG=<model> \
  -e OUTPUT_ADAPTER=github \
  nitless
```

This posts one comment per finding on its line, plus a summary comment. Re-running is safe: the summary is
updated in place and existing findings are not posted twice.

### Other ways to run it

**GitLab:** use the merge request URL and `GITLAB_TOKEN` (scope `api`; `read_api` + `read_repository` if you only want JSON).

```bash
docker run --rm \
  -e MR_URL=https://gitlab.com/<group>/<project>/-/merge_requests/<n> \
  -e GITLAB_TOKEN=<token> -e ANTHROPIC_API_KEY=<key> -e MODEL_STRONG=<model> -e OUTPUT_ADAPTER=gitlab \
  nitless
```

**JSON only:** leave out `OUTPUT_ADAPTER`. Nothing is posted and the result goes to stdout.

```bash
docker run --rm -e MR_URL=... -e GITHUB_TOKEN=... -e ANTHROPIC_API_KEY=... -e MODEL_STRONG=... nitless > review.json
```

**A local repository:** reviews `BASE_REF..HEAD_REF`, no GitHub/GitLab token needed. nitless clones the mounted
repo inside the container and never writes to it.

```bash
docker run --rm -v /path/to/repo:/repo \
  -e LOCAL_REPO=/repo -e BASE_REF=main -e HEAD_REF=my-branch \
  -e ANTHROPIC_API_KEY=... -e MODEL_STRONG=... \
  nitless
```

**Dry run:** `GITHUB_DRY_RUN=on` (or `GITLAB_DRY_RUN=on`) posts nothing and writes the requests it would have
sent to `github-comments.json` (`gitlab-notes.json`) next to `OUTPUT_FILE`.

```bash
mkdir -p out
docker run --rm -v "$PWD/out:/out" \
  -e MR_URL=... -e GITHUB_TOKEN=... -e ANTHROPIC_API_KEY=... -e MODEL_STRONG=... \
  -e OUTPUT_ADAPTER=json,github -e OUTPUT_FILE=/out/review.json -e GITHUB_DRY_RUN=on \
  nitless
```

The container runs as uid 1000. On Linux, add `--user "$(id -u):$(id -g)"` so it can write to `out/`.

**Without Docker:**

```bash
uv sync
cp .env.example .env    # fill in the keys and MODEL_STRONG
uv run nitless --local-repo . --base-ref main
```

A finding looks like this (full report in [samples/py-coupon-checkout.md](samples/py-coupon-checkout.md)):

> 🟠 **app/services/orders.py:59** · major · `correctness` — The discount is 100× too small because
> `coupon.percent_off` (a whole percent, 1–100) is passed to `percent_of`, which expects basis points.
>
> 💡 **Suggestion:** Use `percent_of(subtotal_cents, coupon.percent_off * 100)`, and make the test assert
> `discount_cents == 750`.
>
> 📎 Evidence: callee `app/core/money.py:10-16`, sibling `app/schemas/coupon.py:8`, ... · 🎯 Confidence: 95%

## How it works

1. **Preflight.** Check config, the LLM key and models, and repository access. Fail fast with an exit code.
2. **Fetch** the change via the GitHub/GitLab API and a shallow git fetch (or a local `base..head`).
3. **Triage** without a model: drop lockfiles, generated files and trivial hunks; put risky files first.
4. **Build context** deterministically: repo map, manifests, relevant doc sections, and related code from a
  tree-sitter symbol graph (callers, callees, siblings, tests), packed into a token budget.
5. **Extract the task and conventions** with a fast model. Each convention must cite a `file:line` that is
  checked before use.
6. **Review** with the strong model, plus a separate call that checks the task's acceptance criteria.
  Large diffs are split into units and reviewed in parallel.
7. **Verify.** One call per candidate finding argues against it, then keeps, drops or downgrades it with a
  confidence. Findings below `MIN_CONFIDENCE` or over `MAX_FINDINGS` are dropped.
8. **Publish** through the configured adapters.

Every decision (what context was picked and why, what triage skipped, which findings the verifier killed and
why) is recorded in `context_trace` in the JSON output. [ARCHITECTURE.md](ARCHITECTURE.md) has the details and
the design decisions.

## Output

The JSON result (`schema_version` 1.0, models in [nitless/models.py](nitless/models.py)):


| Field                       | Content                                                                  |
| --------------------------- | ------------------------------------------------------------------------ |
| `status`                    | `ok`, `partial` (diff cut or some units failed) or `error`               |
| `run`                       | repo, SHAs, models, duration, tokens, `cost_usd`                         |
| `summary`                   | short assessment, verdict (`no_issues`, `minor_issues`, `needs_changes`) |
| `requirements`              | acceptance criteria and their status; `null` if no task was found        |
| `findings`                  | see below                                                                |
| `skipped_files`, `warnings` | what was left out and why                                                |
| `error`                     | `{kind, message}` when `status` is `error`                               |
| `context_trace`             | every choice the pipeline made                                           |


Each finding has `file`, `line_start`, `line_end`, `severity` (`critical` / `major` / `minor` / `info`),
`category`, `message`, `rationale`, `evidence`, an optional `suggestion` and `confidence` (0–1). Full examples
are in [samples/](samples/).

### Adapters

`OUTPUT_ADAPTER` is a comma-separated list. Default: `json`.


| Adapter    | Writes to                                                                                |
| ---------- | ---------------------------------------------------------------------------------------- |
| `json`     | `OUTPUT_FILE` or stdout                                                                  |
| `markdown` | `MARKDOWN_FILE` or stdout (only one of `json`/`markdown` can use stdout)                 |
| `github`   | inline review comments + a summary comment. Findings outside the diff go in the summary. |
| `gitlab`   | inline discussions + a summary note. Same behaviour as `github`.                         |


`github` and `gitlab` never post a failed run. To add an adapter, subclass `OutputAdapter` in
`nitless/output/` and register it in `nitless/output/__init__.py`.

## Configuration

Settings come from CLI flags, then environment variables, then `.env`, then defaults. Most have a flag
(`MR_URL` → `--mr-url`); see `uv run nitless --help`. Booleans are `on`/`off`.

**Target** (set `MR_URL` or `LOCAL_REPO`)


| Variable       | Default       | Meaning                                                                    |
| -------------- | ------------- | -------------------------------------------------------------------------- |
| `MR_URL`       |               | GitHub PR or GitLab MR URL (GitHub Enterprise and self-hosted GitLab work) |
| `GITHUB_TOKEN` |               | for GitHub (alias `GH_TOKEN`)                                              |
| `GITLAB_TOKEN` |               | for GitLab (alias `GIT_TOKEN`)                                             |
| `REPO_URL`     | from `MR_URL` | clone URL, if different                                                    |
| `LOCAL_REPO`   |               | path to a local git repo                                                   |
| `BASE_REF`     |               | base ref; required with `LOCAL_REPO`                                       |
| `HEAD_REF`     | `HEAD`        | head ref for `LOCAL_REPO`                                                  |
| `TASK_SOURCE`  |               | task file (`.json`/`.yaml`/`.md`/`.txt`) or URL, e.g. a GitLab issue       |


If `TASK_SOURCE` is unset, nitless uses a `story.json`, `task.json`, `story.md` or `TASK.md` that the change
touches, else the PR or MR description.

**LLM**


| Variable                | Default              | Meaning                                                               |
| ----------------------- | -------------------- | --------------------------------------------------------------------- |
| `LLM_PROVIDER`          | from the key present | see [Providers](#providers)                                           |
| `LLM_API_KEY`           |                      | overrides the provider's own key variable                             |
| `LLM_BASE_URL`          | provider's endpoint  | proxy or self-hosted server; required for `openai_compat`             |
| `MODEL_STRONG`          | required             | review model                                                          |
| `MODEL_FAST`            | `MODEL_STRONG`       | task extraction and conventions                                       |
| `MODEL_VERIFIER`        | `MODEL_STRONG`       | verifier                                                              |
| `MODEL_PRICES`          |                      | extra prices, e.g. `my-model=1.25/10` (USD per 1M in/out tokens)      |
| `LLM_TIMEOUT_S`         | `300`                | per-call timeout                                                      |
| `LLM_MAX_RETRIES`       | `5`                  | retries on transient errors                                           |
| `LLM_RATE_LIMIT_WAIT_S` | `300`                | how long to wait out rate limits (a spent quota exits immediately)    |
| `LLM_MAX_OUTPUT_TOKENS` | `16000`              | completion tokens per call                                            |


**Review**


| Variable                | Default   | Meaning                                                             |
| ----------------------- | --------- | ------------------------------------------------------------------- |
| `SEVERITY_FLOOR`        | `minor`   | lowest severity reported                                            |
| `MIN_CONFIDENCE`        | `0.6`     | drop verified findings below this                                   |
| `MAX_FINDINGS`          | by size   | 3 / 6 / 10 for ≤50 / ≤300 / more changed lines; `0` = no cap        |
| `VERIFY`                | `on`      | run the verifier                                                    |
| `CONVENTIONS`           | `on`      | build the conventions card                                          |
| `MAX_DIFF_LINES`        | `3000`    | changed lines reviewed                                              |
| `ON_OVERSIZE`           | `partial` | over the limit: `partial` reviews risky files first, `fail` exits 6 |
| `PATH_EXCLUDES`         |           | extra gitignore-style patterns to skip, comma-separated             |
| `CONTEXT_BUDGET_TOKENS` | `12000`   | tokens for repo map, manifests, docs                                |
| `RELATED_BUDGET_TOKENS` | `24000`   | tokens for related code                                             |
| `UNIT_BUDGET_TOKENS`    | `12000`   | diff tokens per review call; bigger diffs are split                 |
| `MAX_UNITS`             | `6`       | max review calls per change                                         |
| `TOOLS`                 | `off`     | let reviewer and verifier read the repo (`read_file`, `grep`, ...)  |
| `MAX_TOOL_CALLS`        | `8`       | tool calls per review call                                          |


**Output and runtime**


| Variable                            | Default  | Meaning                                     |
| ----------------------------------- | -------- | ------------------------------------------- |
| `OUTPUT_ADAPTER`                    | `json`   | `json`, `markdown`, `github`, `gitlab`      |
| `OUTPUT_FILE`                       | stdout   | `json` adapter target                       |
| `MARKDOWN_FILE`                     | stdout   | `markdown` adapter target                   |
| `GITHUB_DRY_RUN` / `GITLAB_DRY_RUN` | `off`    | write requests to a file instead of posting |
| `WORKDIR`                           | temp dir | keep the checkout here                      |
| `LOG_LEVEL`                         | `INFO`   | logs go to stderr                           |




### Providers

If `LLM_PROVIDER` is unset, the first key found wins: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
(or `GOOGLE_API_KEY`), `OPENROUTER_API_KEY`.


| Provider        | Key                    | Endpoint                    |
| --------------- | ---------------------- | --------------------------- |
| `anthropic`     | `ANTHROPIC_API_KEY`    | Anthropic API               |
| `openai`        | `OPENAI_API_KEY`       | OpenAI API                  |
| `gemini`        | `GEMINI_API_KEY`       | Gemini, OpenAI-compatible   |
| `github`        | `GITHUB_TOKEN`         | GitHub Models               |
| `openrouter`    | `OPENROUTER_API_KEY`   | OpenRouter                  |
| `ollama`        | none                   | `http://localhost:11434/v1` |
| `openai_compat` | `LLM_API_KEY` optional | `LLM_BASE_URL`              |


Any model with tool calling works.

```bash
LLM_PROVIDER=ollama MODEL_STRONG=<model> uv run nitless --local-repo . --base-ref main
```

`MIN_CONFIDENCE=0.6` was tuned with Opus 5.5 as the verifier; other models calibrate differently
([eval/RESULTS.md](eval/RESULTS.md)).

## Exit codes


| Code | Meaning                                     |
| ---- | ------------------------------------------- |
| 0    | review completed (with or without findings) |
| 1    | internal error                              |
| 2    | invalid configuration                       |
| 3    | repository unreachable or access denied     |
| 4    | PR, MR or `BASE_REF..HEAD_REF` not found    |
| 5    | `TASK_SOURCE` unreadable                    |
| 6    | diff too large (`ON_OVERSIZE=fail`)         |
| 7    | LLM error, including a spent quota          |
| 8    | adapter failed to publish                   |


On failure the JSON result still prints, with `status: "error"` and an `error` block, and no findings.

## Development

```bash
uv sync
uv run pytest
uv run ruff check nitless tests eval scripts
uv run python scripts/render_sample.py
```

```
nitless/
  cli.py, config.py    flags and settings
  pipeline.py          preflight -> fetch -> triage -> context -> review -> verify -> publish
  scm/                 GitHub, GitLab, local git
  context/             project profile, docs, symbol graph, packer, task, conventions
  review/              triage, units, tools, verifier
  prompts/             system prompts, one file per call
  output/              adapters
  llm/                 providers, retries, pricing
```

### Evaluation

```bash
uv run python -m eval.run --label x --judge-provider openai --judge-model <model>
uv run python -m eval.run --label x --cases 'py-*' --repeats 2 --compare baseline
uv run python -m eval.context_check           # no LLM: does the packed context contain what's needed?
```

Results land in `.cache/eval/runs/<label>/`. Full numbers in [eval/RESULTS.md](eval/RESULTS.md).

## Limitations

- Symbol-graph context only for Python, JavaScript/TypeScript and Java. Other languages get the diff, docs and grep.
- GitHub and GitLab only. Issue URLs as `TASK_SOURCE` work for GitLab only.
- No caching between runs.
- No per-repo config file yet.

