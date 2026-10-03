from nitless.diff import parse_diff
from nitless.review.triage import substitutions, triage


def diff(path: str, removed: list[str], added: list[str], context: list[str] = (), status: str = "") -> str:
    body = [f" {c}" for c in context] + [f"-{r}" for r in removed] + [f"+{a}" for a in added]
    old, new = len(context) + len(removed), len(context) + len(added)
    header = f"diff --git a/{path} b/{path}\n{status}--- a/{path}\n+++ b/{path}\n"
    return header + f"@@ -1,{old} +1,{new} @@\n" + "\n".join(body) + "\n"


def levels(text: str) -> dict[str, tuple[str, list[str]]]:
    return {p: (t.level, t.reasons) for p, t in triage(parse_diff(text)).files.items()}


def test_layout_only_changes_are_whitespace():
    reflow = diff("app/a.py", ["result = compute(alpha, beta)"], ["result = compute(", "    alpha,", "    beta,", ")"])
    assert levels(reflow)["app/a.py"] == ("trivial", ["whitespace"])


def test_comments_and_docstrings_are_trivial_but_code_next_to_them_is_not():
    python = diff("app/a.py", [], ['    """Return the total.', "", '    Amounts are in cents."""', "    # fast path"],
                  context=["def total(items):"])
    ts = diff("web/a.ts", ["// old note"], ["/**", " * Formats a price.", " */"])
    mixed = diff("app/b.py", [], ["# note", "x = 1"])
    found = levels(python + ts + mixed)
    assert found["app/a.py"] == ("trivial", ["comment"]) and found["web/a.ts"] == ("trivial", ["comment"])
    assert found["app/b.py"][0] == "normal"


def test_reordered_imports_are_trivial_added_imports_are_not():
    reorder = diff("app/a.py", ["import os", "import json"], ["import json", "import os"])
    added = diff("app/b.py", [], ["import subprocess"])
    found = levels(reorder + added)
    assert found["app/a.py"] == ("trivial", ["imports"]) and found["app/b.py"][0] != "trivial"


def test_a_repeated_substitution_is_a_rename_a_single_one_is_an_edit():
    renamed = "".join(diff(f"app/m{i}.py", [f"x{i} = fetch_user(uid)"], [f"x{i} = load_user(uid)"]) for i in range(3))
    edit = diff("app/pay.py", ["total = price * qty"], ["total = cost * qty"])
    t = triage(parse_diff(renamed + edit))
    assert all(t.level(f"app/m{i}.py") == "trivial" for i in range(3)) and t.renames == {("fetch_user", "load_user")}
    assert t.level("app/pay.py") != "trivial"
    assert substitutions(["if ok and ready:"], ["if ok or ready:"]) == set()  # operators are not renames
    assert substitutions(["flag = True"], ["flag = False"]) == set()


def test_version_bump_docs_generated_and_moves_are_trivial_files():
    bump = diff("package.json", ['  "version": "1.2.0",'], ['  "version": "1.3.0",'])
    dependency = diff("web/package.json", ['    "react": "18.2.0",'], ['    "react": "18.3.1",'])
    docs = diff("docs/guide.md", ["old"], ["new"])
    snapshot = diff("web/__snapshots__/card.test.tsx.snap", ["a"], ["b"])
    moved = ("diff --git a/app/old.py b/app/new.py\nsimilarity index 100%\n"
             "rename from app/old.py\nrename to app/new.py\n")
    found = levels(bump + dependency + docs + snapshot + moved)
    assert found["package.json"] == ("trivial", ["version"]) and found["web/package.json"][0] != "trivial"
    assert found["docs/guide.md"] == ("trivial", ["docs"])
    assert found["web/__snapshots__/card.test.tsx.snap"] == ("trivial", ["generated"])
    assert found["app/new.py"] == ("trivial", ["moved"])


def test_risky_signals():
    removed_check = diff("app/orders.py", ["    if order.status != 'pending':", "        raise Conflict()"], [],
                         context=["def cancel(order):"])
    money = diff("app/report.py", ["    x = 1"], ["    total_cents = sum(o.amount_cents for o in orders)"])
    lock = diff("src/Stock.java", ["    level.add(qty);"], ["    ledger.lock(id);", "    level.add(qty);"])
    test = diff("tests/test_orders.py", ["    assert x"], [])
    found = levels(removed_check + money + lock + test)
    assert found["app/orders.py"] == ("risky", ["removes a check or error handling"])
    assert found["app/report.py"] == ("risky", ["money"])
    assert found["src/Stock.java"] == ("risky", ["concurrency/transactions"])
    assert found["tests/test_orders.py"] == ("normal", [])  # tests are never flagged risky


def test_reviewable_drops_trivial_hunks_and_files():
    text = (
        "diff --git a/app/a.py b/app/a.py\n--- a/app/a.py\n+++ b/app/a.py\n"
        "@@ -1,1 +1,1 @@\n-# old comment\n+# new comment\n"
        "@@ -10,1 +10,1 @@\n-    return a\n+    return b\n"
    ) + diff("README.md", ["a"], ["b"])
    files = parse_diff(text)
    t = triage(files)
    [kept] = t.reviewable(files)
    assert kept.path == "app/a.py" and [h.new_start for h in kept.hunks] == [10]
    assert len(files[0].hunks) == 2  # the original diff is untouched
    assert t.omitted() == {"comment": 1, "docs": 1}
