"""Inline comments from earlier runs whose finding this run no longer reports.

A stale comment is resolved: its text moves into a collapsed block under a "no longer found" line, and its
marker changes from `fp=` to `resolved=`, so a finding that comes back later is posted again as a new comment.
With STALE_COMMENTS=delete a comment nobody replied to is deleted instead.
"""

import re

from nitless.models import ReviewResult

RESOLVED_MARKER = "<!-- nitless:resolved={fp} -->"
FP_MARKER_RE = re.compile(r"\n*<!-- nitless:fp=[0-9a-f]{12} -->\s*$")


def can_clear(result: ReviewResult) -> bool:
    """Only a complete review proves a finding is gone: a partial one may simply not have reached it."""
    return result.status == "ok"


def is_stale(fp: str, file: str | None, current: set[str], result: ReviewResult) -> bool:
    """Not reported this run, on a file this run reviewed (an excluded or skipped file says nothing)."""
    return fp not in current and file not in result.skipped_files


def resolved_body(body: str, fp: str, head_sha: str) -> str:
    original = FP_MARKER_RE.sub("", body).strip()
    return (f"✅ No longer found as of {head_sha[:8]}.\n\n<details><summary>Original comment</summary>\n\n"
            f"{original}\n\n</details>\n\n{RESOLVED_MARKER.format(fp=fp)}")
