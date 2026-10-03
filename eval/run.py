"""Run the reviewer over the eval set and score it.

    uv run python -m eval.run --label baseline --repeats 2
    uv run python -m eval.run --label ctx-v1 --compare baseline --cases 'py-*'

Each case runs the real CLI in a subprocess (the same path a user runs).
Scoring per run:
  - an expected issue is *caught* if an LLM judge says a finding describes it
    (candidates: findings in the same file); each finding matches at most one issue
  - findings that match nothing are false positives; findings overlapping a
    `forbidden` region are also counted as trap hits
  - silent cases pass only with zero findings
  - real-world cases are open-world: unmatched findings are "unverified", not FPs
Results go to .cache/eval/runs/<label>/ (per-run JSON + logs + summary.json).
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from eval.cases import (
    BUILD_DIR,
    EVAL_DIR,
    Anchor,
    CaseSpec,
    Expected,
    build_repo,
    list_repos,
    load_repo_spec,
    selected,
    task_file,
)
from nitless.config import load_settings
from nitless.llm import LLMClient

PROJECT_DIR = EVAL_DIR.parent
RUNS_DIR = BUILD_DIR / "runs"
LINE_SLACK = 3


class RealCase(BaseModel):
    id: str
    mr_url: str
    notes: str = ""
    expected: list[Expected] = Field(default_factory=list)
    forbidden: list[Anchor] = Field(default_factory=list)


@dataclass
class Job:
    case_id: str
    kind: str
    repeat: int
    env: dict[str, str]
    expected: list[Expected]
    forbidden: list[Anchor]
    silent: bool
    noise_budget: int
    open_world: bool = False


@dataclass
class RunScore:
    case_id: str
    kind: str
    repeat: int
    status: str
    caught: list[int] = field(default_factory=list)  # indices of expected issues caught
    judge_reasons: list[str] = field(default_factory=list)
    expected_total: int = 0
    findings: int = 0
    false_positives: int = 0
    unverified: int = 0
    trap_hits: int = 0
    passed: bool = False
    duration_s: float = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- jobs

def synthetic_jobs(patterns: list[str], repeats: int, build: bool = True) -> list[Job]:
    """One job per selected case and repeat; `build=False` reuses the eval repos already built."""
    jobs = []
    for repo in list_repos():
        try:
            spec = load_repo_spec(repo)
        except Exception as e:  # a repo being edited shouldn't block running the others
            print(f"skipping {repo}: invalid cases.yaml ({str(e)[:120]})", file=sys.stderr)
            continue
        chosen = [c for c in spec.cases if selected(c, patterns)]
        if not chosen:
            continue
        path = build_repo(repo) if build else BUILD_DIR / "repos" / repo
        for case in chosen:
            env = {"LOCAL_REPO": str(path), "BASE_REF": "main", "HEAD_REF": f"case/{case.id}"}
            if tf := task_file(repo, case):
                env["TASK_SOURCE"] = str(tf)
            jobs += [_job(case, env, r) for r in range(repeats)]
    return jobs


def _job(case: CaseSpec, env: dict[str, str], repeat: int) -> Job:
    return Job(case.id, case.kind, repeat, env, case.expected, case.forbidden, case.silent, case.noise_budget)


def real_jobs(patterns: list[str], repeats: int) -> list[Job]:
    path = EVAL_DIR / "real.yaml"
    if not path.exists():
        return []
    cases = [RealCase.model_validate(c) for c in yaml.safe_load(path.read_text())["cases"]]
    return [Job(c.id, "real-world", r, {"MR_URL": c.mr_url}, c.expected, c.forbidden, silent=False,
                noise_budget=len(c.expected), open_world=True)
            for c in cases if any(fnmatch.fnmatch(c.id, p) for p in patterns) for r in range(repeats)]


# --------------------------------------------------------------------------- execution

def execute(job: Job, out_dir: Path, extra_env: dict[str, str]) -> dict:
    result = _execute_once(job, out_dir, extra_env)
    if (result.get("error") or {}).get("kind") == "llm":  # transient provider outage: one more try
        result = _execute_once(job, out_dir, extra_env)
    return result


def _stem(job: Job) -> str:
    return f"{job.case_id}__r{job.repeat}"


def load_result(job: Job, run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / f"{_stem(job)}.json").read_text())
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "error", "error": {"kind": "harness", "message": f"no stored result: {e}"}, "findings": []}


def _execute_once(job: Job, out_dir: Path, extra_env: dict[str, str]) -> dict:
    stem = _stem(job)
    out_file = out_dir / f"{stem}.json"
    env = {**os.environ, **extra_env, **job.env, "OUTPUT_ADAPTER": "json", "OUTPUT_FILE": str(out_file)}
    with open(out_dir / f"{stem}.log", "w") as log:
        subprocess.run([sys.executable, "-m", "nitless"], cwd=PROJECT_DIR, env=env, stderr=log,
                       stdout=subprocess.DEVNULL)
    return load_result(job, out_dir)


# --------------------------------------------------------------------------- scoring

class Match(BaseModel):
    expected_index: int
    finding_index: int
    reason: str = Field(description="the shared root cause, quoting the finding")


class Matches(BaseModel):
    matches: list[Match] = Field(default_factory=list)


JUDGE_PROMPT = """You grade an automated code reviewer against a list of known issues in a merge request.
Be strict: this grading decides whether the reviewer is improving, so a generous match is a bug.

A finding MATCHES a known issue if the finding itself identifies the same underlying defect (same
root cause), so that fixing what the finding asks for would fix the known issue. Wording, exact line,
and how specifically it names the downstream consequence may differ: a finding that correctly identifies
the defective change and its general effect matches even if it doesn't name the exact affected caller.
It does NOT match if it is merely in the same file or function, mentions related code, or describes
a different problem. If the finding does not explicitly describe the known issue's defect, it is not a
match. When unsure, do not match. Each finding matches at most one known issue and vice versa.

Call `submit_matches` with every matching pair and a reason quoting the finding (empty list if none)."""


def judge_client(provider: str | None, model: str | None) -> tuple[LLMClient, str]:
    """The judge's own client, so its tokens never mix with the reviewer's."""
    settings = load_settings(local_repo=PROJECT_DIR, base_ref="main", llm_provider=provider, model_strong=model)
    llm = LLMClient(settings)
    llm.preflight([settings.model_strong])
    return llm, settings.model_strong


def judge(llm: LLMClient, model: str, expected: list[Expected], findings: list[dict]) -> list[Match]:
    candidates = [(i, f) for i, f in enumerate(findings) if any(f["file"] in _files(e) for e in expected)]
    if not expected or not candidates:
        return []
    known = "\n".join(f"[{i}] {' or '.join(_files(e))} {e.what}" for i, e in enumerate(expected))
    found = "\n".join(f"[{i}] {f['file']}:{f['line_start']}-{f['line_end']} {f['message']} "
                      f"Rationale: {f['rationale']}" for i, f in candidates)
    result = llm.call_tool(model, [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f"Known issues:\n{known}\n\nReviewer findings:\n{found}"},
    ], "submit_matches", "Submit matching (known issue, finding) pairs.", Matches, max_tokens=2000)
    used_e, used_f, valid = set(), set(), []
    for m in result.matches:
        if (0 <= m.expected_index < len(expected) and 0 <= m.finding_index < len(findings)
                and m.expected_index not in used_e and m.finding_index not in used_f
                and findings[m.finding_index]["file"] in _files(expected[m.expected_index])):
            used_e.add(m.expected_index)
            used_f.add(m.finding_index)
            valid.append(m)
    return valid


def _files(e: Expected) -> list[str]:
    return list(dict.fromkeys([e.file, *(loc.file for loc in e.also_at)]))


def overlaps(f: dict, a: Anchor, slack: int = LINE_SLACK) -> bool:
    return f["file"] == a.file and f["line_start"] <= a.lines[1] + slack and f["line_end"] >= a.lines[0] - slack


def score(job: Job, result: dict, llm: LLMClient, judge_model: str) -> RunScore:
    usage = (result.get("run") or {}).get("usage") or {}
    s = RunScore(job.case_id, job.kind, job.repeat, result.get("status", "error"),
                 expected_total=len(job.expected), duration_s=(result.get("run") or {}).get("duration_s") or 0,
                 prompt_tokens=sum(u["prompt_tokens"] for u in usage.values()),
                 completion_tokens=sum(u["completion_tokens"] for u in usage.values()))
    if s.status == "error":
        s.error = (result.get("error") or {}).get("message", "unknown error")
        return s

    findings = result.get("findings", [])
    matches = judge(llm, judge_model, job.expected, findings)
    matched = {m.finding_index for m in matches}
    s.caught = sorted(m.expected_index for m in matches)
    s.judge_reasons = [f"expected[{m.expected_index}] <- finding[{m.finding_index}]: {m.reason}" for m in matches]
    s.findings = len(findings)
    unmatched = [f for i, f in enumerate(findings) if i not in matched]
    s.trap_hits = sum(1 for f in unmatched if any(overlaps(f, a) for a in job.forbidden))
    if job.open_world:
        s.false_positives = s.trap_hits
        s.unverified = len(unmatched) - s.trap_hits
    else:
        s.false_positives = len(unmatched)
    extra_allowed = max(0, job.noise_budget - len(job.expected))
    s.passed = (len(s.caught) == len(job.expected) and s.trap_hits == 0
                and (s.findings <= job.noise_budget if job.silent else s.false_positives <= extra_allowed))
    return s


# --------------------------------------------------------------------------- reporting

def summarize(scores: list[RunScore]) -> dict:
    ok = [s for s in scores if s.status != "error"]
    closed = [s for s in ok if s.kind != "real-world"]
    exp = sum(s.expected_total for s in closed)
    caught = sum(len(s.caught) for s in closed)
    fp = sum(s.false_positives for s in closed)
    silent = [s for s in closed if s.kind in ("correct-here", "out-of-scope", "clean", "nit-bait")]
    by_kind: dict[str, dict] = defaultdict(lambda: {"runs": 0, "passed": 0, "caught": 0, "expected": 0, "fp": 0})
    for s in ok:
        k = by_kind[s.kind]
        k["runs"] += 1
        k["passed"] += s.passed
        k["caught"] += len(s.caught)
        k["expected"] += s.expected_total
        k["fp"] += s.false_positives
    return {
        "runs": len(scores),
        "errors": len(scores) - len(ok),
        "recall": round(caught / exp, 3) if exp else None,
        "precision": round(caught / (caught + fp), 3) if caught + fp else None,
        "silence_rate": round(sum(s.findings == 0 for s in silent) / len(silent), 3) if silent else None,
        "trap_hits": sum(s.trap_hits for s in closed),
        "pass_rate": round(sum(s.passed for s in closed) / len(closed), 3) if closed else None,
        "real_world_caught": f"{sum(len(s.caught) for s in ok if s.kind == 'real-world')}/"
                             f"{sum(s.expected_total for s in ok if s.kind == 'real-world')}",
        "avg_duration_s": round(sum(s.duration_s for s in ok) / len(ok), 1) if ok else None,
        "tokens": {"prompt": sum(s.prompt_tokens for s in scores),
                   "completion": sum(s.completion_tokens for s in scores)},
        "by_kind": dict(sorted(by_kind.items())),
    }


def print_report(label: str, summary: dict, scores: list[RunScore], baseline: dict | None) -> None:
    print(f"\n=== {label} ===")
    for s in sorted(scores, key=lambda s: (s.case_id, s.repeat)):
        mark = "PASS" if s.passed else ("ERR " if s.error else "fail")
        detail = s.error or (f"caught {len(s.caught)}/{s.expected_total}  findings {s.findings}  fp {s.false_positives}"
                             + (f"  unverified {s.unverified}" if s.unverified else "")
                             + (f"  TRAP {s.trap_hits}" if s.trap_hits else ""))
        print(f"  {mark}  {s.case_id:<34} r{s.repeat}  {s.kind:<17} {detail}")
    print("\n  by kind:")
    for kind, k in summary["by_kind"].items():
        print(f"    {kind:<17} passed {k['passed']}/{k['runs']}   caught {k['caught']}/{k['expected']}   fp {k['fp']}")
    print()
    for key in ("recall", "precision", "silence_rate", "pass_rate", "trap_hits", "real_world_caught",
                "avg_duration_s", "errors"):
        delta = ""
        if baseline and isinstance(summary[key], (int, float)) and isinstance(baseline.get(key), (int, float)):
            delta = f"   ({summary[key] - baseline[key]:+.3f} vs baseline)"
        print(f"  {key:<18} {summary[key]}{delta}")
    print(f"  {'tokens':<18} {summary['tokens']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", default=time.strftime("run-%Y%m%d-%H%M%S"))
    p.add_argument("--cases", default="*", help="comma-separated glob(s) over case ids (`*` skips the big composed "
                   "cases; select them by name, e.g. `*-big-mr`)")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--parallel", type=int, default=6)
    p.add_argument("--no-real", action="store_true", help="skip real-world MRs from eval/real.yaml")
    p.add_argument("--judge-provider", help="LLM provider for the judge (default: the configured one)")
    p.add_argument("--judge-model", help="judge model, ideally another family than the reviewer "
                   "(default: the provider's strong model)")
    p.add_argument("--compare", help="label of a previous run to diff against")
    p.add_argument("--rescore", metavar="LABEL", help="re-judge the stored reviews of LABEL without re-running them")
    p.add_argument("--retry-errors", action="store_true",
                   help="reuse the stored results of --label and re-run only the reviews that errored")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="extra env for the reviewer")
    args = p.parse_args()

    patterns = args.cases.split(",")
    extra_env = dict(kv.split("=", 1) for kv in args.set)
    jobs = synthetic_jobs(patterns, args.repeats) + ([] if args.no_real else real_jobs(patterns, args.repeats))
    if not jobs:
        sys.exit("no cases selected")
    out_dir = RUNS_DIR / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"running {len(jobs)} reviews ({args.parallel} in parallel) -> {out_dir}", flush=True)

    judge_llm, args.judge_model = judge_client(args.judge_provider, args.judge_model)

    quota_exhausted = threading.Event()

    def review(job: Job) -> dict:
        if args.rescore:
            return load_result(job, RUNS_DIR / args.rescore)
        if args.retry_errors and (stored := load_result(job, out_dir)).get("status") != "error":
            return stored
        if quota_exhausted.is_set():  # every further call would fail the same way; don't burn time on it
            return {"status": "error", "error": {"kind": "llm", "message": "skipped: LLM quota exhausted"}}
        result = execute(job, out_dir, extra_env)
        if "quota exhausted" in ((result.get("error") or {}).get("message") or ""):
            quota_exhausted.set()
        return result

    def run_one(job: Job) -> RunScore:
        result = review(job)
        s = score(job, result, judge_llm, args.judge_model)
        print(f"  done {job.case_id} r{job.repeat}: {'PASS' if s.passed else 'fail'}", flush=True)
        return s

    with ThreadPoolExecutor(args.parallel) as pool:
        scores = list(pool.map(run_one, jobs))

    summary = summarize(scores)
    summary["label"] = args.label
    summary["reviewer_env"] = extra_env
    summary["judge_tokens"] = {m: u.model_dump() for m, u in judge_llm.usage.items()}
    (out_dir / "summary.json").write_text(json.dumps({**summary, "scores": [asdict(s) for s in scores]}, indent=2))
    baseline = None
    if args.compare:
        baseline = json.loads((RUNS_DIR / args.compare / "summary.json").read_text())
    print_report(args.label, summary, scores, baseline)


if __name__ == "__main__":
    main()
