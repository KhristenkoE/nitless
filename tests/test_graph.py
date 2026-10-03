import subprocess
from pathlib import Path

from nitless.context import build_related
from nitless.context.graph import Snippet, SymbolGraph, contract
from nitless.context.index import RepoIndex
from nitless.context.packer import pack
from nitless.context.symbols import parse
from nitless.diff import compute_diff


def commit_change(root: Path, base: dict[str, str], head: dict[str, str]) -> SymbolGraph:
    """A repo with `base` committed, then `head` (file -> new text) committed on top."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    for files in (base, head):
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "c"], check=True)
    files = subprocess.run([*git, "ls-files"], check=True, capture_output=True, text=True).stdout.split()
    return SymbolGraph(RepoIndex(root, files, "HEAD~1"), compute_diff(root, "HEAD~1", "HEAD"))


MONEY = "def to_cents(amount):\n    return int(amount * 100)\n"
CALLERS = {
    "app/money.py": MONEY,
    "app/billing.py": "from app.money import to_cents\n\n\ndef charge(order):\n    return to_cents(order.total)\n",
    "app/legacy.py": "from app.old_money import to_cents\n\n\ndef refund(order):\n    return to_cents(order.total)\n",
    "app/old_money.py": "def to_cents(amount):\n    return round(amount * 100)\n",
    "app/report.py": "# to_cents is documented in the ADR\nVALUE = 1\n",
    "app/misc.py": "def cents(price):\n    return price.to_cents()\n",
    "tests/test_money.py": "from app.money import to_cents\n\n\ndef test_to_cents():\n    assert to_cents(1) == 100\n",
}


def test_callers_of_a_signature_change_are_confirmed_by_imports(tmp_path):
    graph = commit_change(tmp_path, CALLERS, {"app/money.py": MONEY.replace("(amount)", "(amount, currency)")})
    [symbol] = graph.symbols
    assert symbol.change == "signature" and symbol.old_signature == "def to_cents(amount):"

    found = {s.path: s for s in graph.callers()}
    # legacy.py binds to_cents to another module, report.py only mentions it, old_money.py defines its own
    assert set(found) == {"app/billing.py", "app/misc.py", "tests/test_money.py"}
    billing, misc = found["app/billing.py"], found["app/misc.py"]
    assert billing.kind == "caller" and billing.ranges == ((4, 5),)
    assert "imports to_cents from app.money" in billing.reason and "signature changed" in billing.reason
    assert "unconfirmed" in misc.reason and billing.score > misc.score
    assert found["tests/test_money.py"].kind == "test"
    assert graph.notes == []


def test_callee_contract_and_untested_note(tmp_path):
    pricing = ('def apply_discount(total, percent):\n    """Discounted total; percent is 0-100, not a fraction."""\n'
               "    return total * (100 - percent) / 100\n")
    billing = "def charge(order):\n    return order.total\n"
    graph = commit_change(tmp_path, {"app/pricing.py": pricing, "app/billing.py": billing}, {
        "app/billing.py": "from app.pricing import apply_discount\n\n\ndef charge(order):\n"
                          "    return apply_discount(order.total, 0.1)\n"})
    callee = next(s for s in graph.collect() if s.path == "app/pricing.py")
    assert callee.kind == "callee" and callee.ranges == ((1, 3),)  # docstring and signature included
    assert "function apply_discount used by the change in app/billing.py" in callee.reason
    assert graph.notes == ["no test references the changed symbols of app/billing.py: charge"]


def test_contract_of_a_large_class_is_a_skeleton():
    methods = "".join(f"    def m{i}(self, x):\n        y = x + {i}\n        return y\n\n" for i in range(15))
    src = parse("big.py", f"class Big:\n    '''Docs.'''\n\n{methods}")
    ranges = contract(src, src.named("Big")[0])
    assert ranges[0] == (1, 3) and (4, 4) in ranges and len(ranges) == 16  # prologue + one line per method


def test_pack_merges_overlaps_and_respects_the_budget():
    lines = [f"line {n}" for n in range(1, 201)]
    source = parse("a.py", "\n".join(lines))
    snippets = [
        Snippet("caller", "a.py", ((1, 5),), "caller one", 90),
        Snippet("callee", "a.py", ((4, 8),), "callee two", 80),
        Snippet("sibling", "a.py", ((100, 200),), "big sibling", 40),
        Snippet("test", "a.py", ((20, 22),), "a test", 60),
    ]
    related = pack(snippets, lambda path: source, budget_tokens=60, symbols=[], notes=[])
    assert [(i.kind, i.source, i.reason) for i in related.included] == [
        ("caller", "a.py:1-8", "caller one; callee two"), ("test", "a.py:20-22", "a test")]
    assert [i.source for i in related.dropped] == ["a.py:100-200"]
    assert related.tokens <= 60
    rendered = related.render()
    assert '<context kind="caller" source="a.py:1-8" reason="caller one; callee two">' in rendered
    assert "     8  line 8" in rendered
    assert [row["status"] for row in related.trace()["items"]] == ["included", "included", "dropped"]


def test_build_related_never_raises(tmp_path):
    related = build_related(tmp_path / "missing", [], "HEAD", [], 1000)
    assert related.included == [] and related.render() == ""
