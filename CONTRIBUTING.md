# Contributing

```bash
uv sync
uv run ruff check nitless tests eval scripts
uv run pytest
```

The tests never call a model or the network. Changes to prompts, retrieval, filtering or model defaults change review quality, so they come with an eval run (`eval/RESULTS.md` explains the method):

```bash
uv run python -m eval.run --label my-change --repeats 2 --judge-provider openai --judge-model <model>
uv run python -m eval.run --compare my-change
```

Use a judge model from a different family than the reviewer. Add a row to `eval/RESULTS.md` with the numbers.

Bug reports: say which provider and model you used, and remove keys and tokens from logs. For a wrong or missed finding, a link to a public pull request helps most.
