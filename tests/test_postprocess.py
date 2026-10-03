from nitless.diff import parse_diff
from nitless.review.postprocess import dedupe_units, summarize, validate
from nitless.review.schema import CandidateFinding

DIFF = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -5,3 +5,4 @@
 a = 1
+b = a / 0
 c = 2
 d = 3
"""


def finding(**kw) -> CandidateFinding:
    base = dict(file="app.py", line_start=6, severity="major", category="correctness",
                message="Division by zero", rationale="crashes on import", confidence=0.9)
    return CandidateFinding(**{**base, **kw})


def test_keeps_valid_and_drops_out_of_diff():
    files = parse_diff(DIFF)
    kept, warnings = validate(
        [finding(), finding(file="other.py"), finding(line_start=99), finding()],  # last one is a duplicate
        files, severity_floor="minor")
    assert [f.line_start for f in kept] == [6]
    assert len(warnings) == 2


def test_severity_floor_and_confidence():
    files = parse_diff(DIFF)
    kept, _ = validate([finding(severity="minor")], files, severity_floor="major")
    assert kept == []
    kept, _ = validate([finding(confidence=0.3)], files, severity_floor="minor", min_confidence=0.5)
    assert kept == []


def test_verdict_is_computed_not_trusted():
    files = parse_diff(DIFF)
    kept, _ = validate([finding()], files, "minor")
    assert summarize("x", kept).verdict == "needs_changes"
    assert summarize("clean", []).verdict == "no_issues"


def test_double_encoded_tool_arguments_are_unwrapped():
    from nitless.llm import decode_arguments

    assert decode_arguments('{"matches": "{\\"matches\\": [1]}"}') == {"matches": [1]}
    assert decode_arguments('"{\\"a\\": 1}"') == {"a": 1}
    assert decode_arguments('{"msg": "{not json"}') == {"msg": "{not json"}


def test_units_repeating_each_other_keep_the_stronger_copy():
    weak = finding(line_start=7, confidence=0.6, category="reliability", message="Division by zero on import")
    other_line = finding(line_start=40)
    same_unit_twin = finding(line_start=6, message="Also divides by zero")
    kept, notes = dedupe_units([[weak, other_line], [finding(), same_unit_twin], [finding(file="b.py")]])
    assert kept == [other_line, finding(), same_unit_twin, finding(file="b.py")]  # original order
    assert notes == ["dropped finding on app.py:7 from review part 1: it repeats the finding at app.py:6"]
