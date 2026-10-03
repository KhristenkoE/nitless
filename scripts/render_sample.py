"""Regenerate samples/ from the stored review in tests/fixtures.

Usage: uv run python scripts/render_sample.py
"""

from pathlib import Path

from nitless.models import ReviewResult
from nitless.output.markdown import render

ROOT = Path(__file__).resolve().parent.parent
CASE = "py-coupon-checkout"

result = ReviewResult.model_validate_json((ROOT / "tests" / "fixtures" / f"{CASE}.json").read_text())
(ROOT / "samples" / f"{CASE}.json").write_text(result.model_dump_json(indent=2) + "\n")
(ROOT / "samples" / f"{CASE}.md").write_text(render(result, None))
