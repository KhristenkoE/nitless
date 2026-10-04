#!/usr/bin/env bash
# Entry point of the nitless GitHub Action (action.yml): run the review, publish outputs and the job summary,
# and apply fail-on. Inputs arrive as environment variables; empty ones are unset so defaults apply.
set -euo pipefail

if [[ -z "${MR_URL:-}" ]]; then
  echo "::error::nitless reviews pull requests: run it on a pull_request event or set pull-request-url"
  exit 1
fi

for var in LLM_API_KEY LLM_BASE_URL MODEL_FAST MODEL_VERIFIER; do
  [[ -n "${!var:-}" ]] || unset "$var"
done
[[ -n "${LLM_API_KEY:-}" ]] && echo "::add-mask::$LLM_API_KEY"

while IFS= read -r line; do  # extra settings, KEY=VALUE per line
  line="${line#"${line%%[![:space:]]*}"}"
  [[ -z "$line" || "$line" == \#* ]] && continue
  [[ "$line" == *=* ]] || { echo "::error::env input lines must be KEY=VALUE, got: ${line%%=*}"; exit 1; }
  export "${line?}"
done <<< "${NITLESS_EXTRA_ENV:-}"

out="${RUNNER_TEMP:-/tmp}/nitless"
mkdir -p "$out"
export OUTPUT_ADAPTER="json,markdown,github" OUTPUT_FILE="$out/review.json" MARKDOWN_FILE="$out/review.md"

status=0
uv run --quiet --frozen --no-dev --project "$GITHUB_ACTION_PATH" nitless || status=$?

{
  [[ -f "$out/review.md" ]] && cat "$out/review.md"
  if [[ -f "$out/github-comments.json" ]]; then
    printf '\n<details><summary>Dry run: requests that were not sent</summary>\n\n```json\n'
    cat "$out/github-comments.json"
    printf '\n```\n\n</details>\n'
  fi
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "result=$out/review.json" >> "$GITHUB_OUTPUT"
[[ -f "$out/review.json" ]] || exit "$((status ? status : 1))"

python3 - "$out/review.json" "${NITLESS_FAIL_ON:-never}" "$status" <<'PY'
import json, os, sys

path, fail_on, status = sys.argv[1], sys.argv[2], int(sys.argv[3])
order = {"info": 0, "minor": 1, "major": 2, "critical": 3}
result = json.load(open(path))
findings = result.get("findings", [])
verdict = (result.get("summary") or {}).get("verdict", "")
with open(os.environ["GITHUB_OUTPUT"], "a") as out:
    out.write(f"verdict={verdict}\nfindings={len(findings)}\n")
if status:
    error = result.get("error") or {}
    print(f"::error::nitless failed (exit {status}): {error.get('kind', '')}: {error.get('message', '')}"[:1000])
    sys.exit(status)
if fail_on not in (*order, "never"):
    print(f"::error::fail-on must be critical, major, minor or never, not {fail_on!r}")
    sys.exit(1)
if fail_on != "never":
    blocking = [f for f in findings if order[f["severity"]] >= order[fail_on]]
    if blocking:
        print(f"::error::{len(blocking)} finding(s) at or above {fail_on}")
        sys.exit(1)
PY
