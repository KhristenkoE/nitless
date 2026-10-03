"""Re-run only the verification stage over the stored reviews of an eval run, and score it like eval.run.

    uv run python -m eval.reverify --source bo-opus --label rv-astra \\
        --set MODEL_VERIFIER=claude-sonnet-5-5
    uv run python -m eval.reverify --source /path/to/runs/m5-opus --label rv-m5-cap0 --set MAX_FINDINGS=0

For every case/repeat of the source run, the context is rebuilt the way the pipeline builds it (checkout, file
selection, profile, related code, task intent, conventions card), the stored findings become the candidates
(they are post-`validate`, i.e. exactly the verifier's input), and only the verifier and the post-filter run.
The reviewer is not called, so a variant costs a fraction of a full eval. The conventions card is taken from
the stored trace when the source run built one (the rules the reviewer saw); otherwise it is built once per case
and cached with the task intent under .cache/eval/reverify-cache/. The assessment is not restated (not scored).

Scoring reuses eval.run (same judge, same pass rules). The report adds verifier cost and, against the source
run's judge matches, the true findings the verifier dropped and the false positives it kept.
"""

import argparse
import json
import pickle
import re
import sys
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from eval.cases import BUILD_DIR, list_repos
from eval.run import (
    RUNS_DIR,
    Job,
    judge_client,
    load_result,
    print_report,
    real_jobs,
    score,
    summarize,
    synthetic_jobs,
)
from nitless import pipeline
from nitless.config import Settings, load_settings
from nitless.context import Profile, RelatedContext
from nitless.context.conventions import ConventionsCard, Rule
from nitless.context.intent import Intent, load_task_source
from nitless.diff import FileDiff
from nitless.errors import ReviewerError
from nitless.llm import LLMClient
from nitless.models import ChangeRequest, Finding, Requirements
from nitless.review import requirements, verifier
from nitless.review.postprocess import summarize as summarize_review
from nitless.scm import make_provider

CACHE_DIR = BUILD_DIR / "reverify-cache"


@dataclass
class CaseContext:
    change: ChangeRequest
    repo_dir: Path
    files: list[FileDiff]
    profile: Profile
    related: RelatedContext
    intent: Intent
    card: ConventionsCard | None


class Contexts:
    """Per-case context, built once and shared by the repeats of a case (and cached on disk across variants)."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self._built: dict[str, CaseContext] = {}
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def get(self, job: Job, settings: Settings, llm: LLMClient, stored: dict) -> CaseContext:
        with self._locks[job.case_id]:
            if job.case_id not in self._built:
                self._built[job.case_id] = self._build(job, settings, llm, stored)
            return self._built[job.case_id]

    def _build(self, job: Job, settings: Settings, llm: LLMClient, stored: dict) -> CaseContext:
        explicit = load_task_source(settings.task_source, settings.gitlab_token, settings.mr_url) \
            if settings.task_source else None
        provider = make_provider(settings)
        change = provider.fetch_change()
        repo_dir = provider.checkout(change, self.workdir / job.case_id)
        sel = pipeline.select_files(repo_dir, change, settings, explicit)
        task, files = sel.task, sel.files
        profile, related = pipeline.build_context(repo_dir, files, change.base_sha, settings, sel.index)
        cache = CACHE_DIR / f"{job.case_id}-{change.head_sha[:12]}.pkl"
        if cache.exists():
            intent, card = pickle.loads(cache.read_bytes())
        else:
            intent, card = pipeline.understand(settings, llm, task, files, profile, related)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps((intent, card)))
        stored_card = ((stored.get("context_trace") or {}).get("conventions") or {}).get("rules")
        if stored_card is not None:  # the card the reviewer actually saw
            card = ConventionsCard([Rule(r["tag"], r["area"], r["topic"], r["rule"], r["evidence"])
                                    for r in stored_card])
        return CaseContext(change, repo_dir, files, profile, related, intent, card)


def reverify(job: Job, stored: dict, extra_env: dict[str, str], contexts: Contexts,
             replay: dict | None = None) -> dict:
    if stored.get("status") == "error":
        return stored
    env = {**job.env, **extra_env}
    settings = load_settings(**{k.lower(): v for k, v in env.items()})
    findings = [Finding.model_validate(f) for f in stored["findings"]]
    if replay is not None:  # verdicts of an earlier reverify run: only the post-filter runs
        verification = pipeline.post_filter(settings, replayed_checks(findings, replay),
                                            replay["context_trace"]["verification"]["changed_lines"])
        return result_of(stored, verification, {}, extra_env)
    context_llm = LLMClient(settings)  # intent and card (fast model), when not cached
    context_llm.preflight([settings.model_fast])
    ctx = contexts.get(job, settings, context_llm, stored)
    material = verifier.build_material(ctx.repo_dir, ctx.change, ctx.files, ctx.profile, ctx.related, ctx.intent,
                                       ctx.card.render() if ctx.card else "")
    llm = LLMClient(settings)  # its usage is the verifier's cost
    if settings.verify:
        llm.preflight([settings.model_verifier])
    verification = pipeline.verify(settings, llm, findings, material)
    return result_of(stored, verification, {m: u.model_dump() for m, u in llm.usage.items()}, extra_env)


def replayed_checks(findings: list[Finding], replay: dict) -> list[verifier.Check]:
    rows = {r["id"]: r for r in replay["context_trace"]["verification"]["findings"]}
    return [verifier.Check(f, verifier.Verdict.model_validate(rows[f.id]["verdict"])
                           if rows.get(f.id, {}).get("verdict") else None, rows.get(f.id, {}).get("error"))
            for f in findings]


def result_of(stored: dict, verification: verifier.Verification, usage: dict, extra_env: dict[str, str]) -> dict:
    """The stored review with the verification stage's outcome in place of its findings."""
    reqs = Requirements.model_validate(stored["requirements"]) if stored.get("requirements") else None
    reqs = requirements.dispute(reqs, verification.refuted_criteria()) if reqs else None
    trace = {**(stored.get("context_trace") or {}), "verification": verification.trace()}
    return {**stored,
            "summary": summarize_review((stored.get("summary") or {}).get("assessment", ""), verification.published,
                                        reqs).model_dump(),
            "requirements": reqs.model_dump() if reqs else None,
            "findings": [f.model_dump() for f in verification.published],
            "warnings": [*stored.get("warnings", []), *verification.warnings],
            "context_trace": trace,
            "reverify": {"usage": usage, "duration_s": verification.duration_s, "env": extra_env}}


# --------------------------------------------------------------------------- source-relative diagnostics

def fates(job: Job, source_score: dict | None, source: dict, result: dict) -> tuple[list[dict], list[dict]]:
    """(true findings of the source run that are no longer published, false positives that still are)."""
    if not source_score or result.get("status") == "error":
        return [], []
    matched = {int(m[1]) for r in source_score["judge_reasons"] if (m := re.search(r"finding\[(\d+)\]", r))}
    published = {f["id"] for f in result["findings"]}
    rows = {r["id"]: r for r in (result.get("context_trace") or {}).get("verification", {}).get("findings", [])}
    lost, kept = [], []
    for i, f in enumerate(source["findings"]):
        row = rows.get(f["id"], {})
        verdict = row.get("verdict") or {}
        entry = {"case": f"{job.case_id} r{job.repeat}", "kind": job.kind, "file": f"{f['file']}:{f['line_start']}",
                 "category": f["category"], "message": f["message"], "dropped_by": row.get("dropped_by"),
                 "reason": verdict.get("reason"), "confidence": verdict.get("confidence"),
                 "justification": verdict.get("justification")}
        if i in matched and f["id"] not in published:
            lost.append(entry)
        elif i not in matched and f["id"] in published and not job.open_world:
            kept.append(entry)
    return lost, kept


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="label of a stored run (under RUNS_DIR) or its directory")
    p.add_argument("--label", default=time.strftime("rv-%Y%m%d-%H%M%S"))
    p.add_argument("--cases", default="*", help="comma-separated glob(s) over case ids")
    p.add_argument("--repeats", type=int, help="only the first N repeats of each case (default: all stored)")
    p.add_argument("--repeat", type=int, help="only this repeat of each case (e.g. a holdout for a threshold)")
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--no-real", action="store_true", help="skip real-world MRs from eval/real.yaml")
    p.add_argument("--judge-provider", help="LLM provider for the judge (default: the configured one)")
    p.add_argument("--judge-model", help="judge model, ideally another family than the reviewer "
                   "(default: the provider's strong model)")
    p.add_argument("--compare", help="label or directory of a run to diff against (default: the source)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="extra env for the verifier")
    p.add_argument("--replay", metavar="LABEL", help="reuse the verdicts of an earlier reverify run (no verifier "
                                                     "calls): tunes MIN_CONFIDENCE / MAX_FINDINGS for free")
    args = p.parse_args()

    source_dir = Path(args.source) if "/" in args.source else RUNS_DIR / args.source
    source_summary = json.loads((source_dir / "summary.json").read_text())
    source_scores = {(s["case_id"], s["repeat"]): s for s in source_summary["scores"]}
    patterns = args.cases.split(",")
    repeats = args.repeats or 1 + max(s["repeat"] for s in source_summary["scores"])
    if args.repeat is not None:
        source_scores = {k: s for k, s in source_scores.items() if k[1] == args.repeat}
    if not (BUILD_DIR / "repos").exists() or not all((BUILD_DIR / "repos" / r).exists() for r in list_repos()):
        sys.exit("eval repos are not built: run `uv run python -m eval.cases` first")
    jobs = synthetic_jobs(patterns, repeats, build=False) + ([] if args.no_real else real_jobs(patterns, repeats))
    jobs = [j for j in jobs if (j.case_id, j.repeat) in source_scores]
    if not jobs:
        sys.exit("no stored reviews selected")
    extra_env = dict(kv.split("=", 1) for kv in args.set)
    out_dir = RUNS_DIR / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"re-verifying {len(jobs)} stored reviews of {source_dir.name} ({args.parallel} in parallel) -> {out_dir}",
          flush=True)

    judge_llm, args.judge_model = judge_client(args.judge_provider, args.judge_model)
    lost: list[dict] = []
    kept_fp: list[dict] = []
    cost: list[dict] = []
    lock = threading.Lock()

    with tempfile.TemporaryDirectory(prefix="reverify-") as workdir:
        contexts = Contexts(Path(workdir))

        def run_one(job: Job):
            stored = load_result(job, source_dir)
            replay = load_result(job, RUNS_DIR / args.replay) if args.replay else None
            try:
                result = reverify(job, stored, extra_env, contexts, replay)
            except ReviewerError as e:
                result = {"status": "error", "error": {"kind": e.kind, "message": str(e)}, "findings": []}
            stem = f"{job.case_id}__r{job.repeat}"
            (out_dir / f"{stem}.json").write_text(json.dumps(result, indent=2, default=str))
            s = score(job, result, judge_llm, args.judge_model)
            a, b = fates(job, source_scores.get((job.case_id, job.repeat)), stored, result)
            with lock:
                lost.extend(a)
                kept_fp.extend(b)
                if "reverify" in result:
                    cost.append({"duration_s": result["reverify"]["duration_s"],
                                 "candidates": len(stored["findings"]), "usage": result["reverify"]["usage"]})
            print(f"  done {job.case_id} r{job.repeat}: {'PASS' if s.passed else 'fail'}"
                  f" ({len(stored['findings'])} -> {len(result['findings'])} findings)", flush=True)
            return s

        with ThreadPoolExecutor(args.parallel) as pool:
            scores = list(pool.map(run_one, jobs))

    summary = summarize(scores)
    tokens = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    for c in cost:
        for model, u in c["usage"].items():
            for k in tokens[model]:
                tokens[model][k] += u[k]
    summary.update({
        "label": args.label, "source": str(source_dir), "reviewer_env": extra_env,
        "verifier": {"tokens": dict(tokens), "reviews": len(cost),
                     "tokens_per_review": round(sum(t["prompt_tokens"] + t["completion_tokens"]
                                                    for t in tokens.values()) / max(1, len(cost))),
                     "avg_duration_s": round(sum(c["duration_s"] for c in cost) / max(1, len(cost)), 1)},
        "true_findings_dropped": lost, "false_positives_kept": kept_fp,
        "judge_tokens": {m: u.model_dump() for m, u in judge_llm.usage.items()},
    })
    (out_dir / "summary.json").write_text(json.dumps({**summary, "scores": [asdict(s) for s in scores]}, indent=2))
    compare_dir = (Path(args.compare) if "/" in args.compare else RUNS_DIR / args.compare) if args.compare \
        else source_dir
    print_report(args.label, summary, scores, json.loads((compare_dir / "summary.json").read_text()))
    print(f"  {'verifier':<18} {summary['verifier']}")
    for title, rows in (("true findings dropped", lost), ("false positives kept", kept_fp)):
        print(f"\n  {title}: {len(rows)}")
        for r in rows:
            print(f"    {r['case']:<34} {r['file']} [{r['category']}] {r['message'][:90]}\n"
                  f"      -> {r['dropped_by'] or 'kept'} {r['reason']} {r['confidence']}: {r['justification']}")


if __name__ == "__main__":
    main()
