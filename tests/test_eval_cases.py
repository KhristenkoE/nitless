import subprocess
from pathlib import Path

import pytest
import yaml

from eval import cases

SPEC = {
    "language": "python",
    "cases": [
        {"id": "bug", "kind": "diff-bug", "notes": "n", "title": "T-1: pricing", "description": "Prices.",
         "expected": [{"file": "app/pricing.py", "lines": [2, 2], "what": "wrong rate"}],
         "context": ["app/rates.py"]},
        {"id": "quiet", "kind": "nit-bait", "notes": "n", "title": "T-2: health", "max_findings": 1,
         "forbidden": [{"file": "app/health.py", "lines": [1, 1], "what": "naming"}]},
        {"id": "big", "kind": "composed", "notes": "n", "title": "Release", "description": "Two tickets.",
         "compose": ["bug", "quiet"]},
    ],
}


def write(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(cases, "REPOS_DIR", tmp_path / "repos")
    monkeypatch.setattr(cases, "BUILD_DIR", tmp_path / "build")
    root = tmp_path / "repos" / "demo"
    write(root, {"cases.yaml": yaml.safe_dump(SPEC), "base/app/pricing.py": "RATE = 1\n",
                 "base/app/rates.py": "X = 1\n", "base/app/health.py": "ok = 1\n", "base/README.md": "# Demo\n",
                 "cases/bug/app/pricing.py": "RATE = 1\nTAX = 2\n", "cases/quiet/app/health.py": "okay = 1\n",
                 "cases/big/README.md": "# Demo\n\nLicensed under Apache-2.0.\n"})
    return root


def test_a_composed_case_unites_its_components(repo):
    spec = cases.load_repo_spec("demo")
    big = spec.cases[2]
    assert [e.file for e in big.expected] == ["app/pricing.py"] and [a.file for a in big.forbidden] == ["app/health.py"]
    assert big.context == ["app/rates.py"] and big.noise_budget == 1 + 1 and not big.silent
    assert big.description == "Two tickets.\n\n## T-1: pricing\n\nPrices.\n\n## T-2: health"

    assert cases.validate_repo("demo") == []
    changed = subprocess.run(["git", "diff", "--name-only", "main", "case/big"], cwd=cases.BUILD_DIR / "repos" / "demo",
                             capture_output=True, text=True, check=True).stdout.split()
    assert changed == ["README.md", "app/health.py", "app/pricing.py"]  # both components plus the filler

    assert [c.id for c in spec.cases if cases.selected(c, ["*"])] == ["bug", "quiet"]  # big cases run when named
    assert cases.selected(big, ["*big*"])


def test_composed_overlays_must_not_overlap(repo):
    write(repo, {"cases/big/app/pricing.py": "RATE = 3\n"})
    with pytest.raises(ValueError, match="app/pricing.py is changed by both bug and big"):
        cases.build_repo("demo")


def test_components_must_exist(repo):
    spec = yaml.safe_load((repo / "cases.yaml").read_text())
    spec["cases"][2]["compose"] = ["bug", "missing"]
    (repo / "cases.yaml").write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError, match="unknown or composed components"):
        cases.load_repo_spec("demo")
