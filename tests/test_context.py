import json
import subprocess
from pathlib import Path

from nitless.context import ContextItem, build_profile
from nitless.context.docs import path_terms, split_sections
from nitless.context.profile import fit_budget


def make_repo(root: Path, files: dict[str, str]) -> Path:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    return root


def by_source(profile) -> dict[str, ContextItem]:
    return {item.source: item for item in profile.included}


def test_package_json_and_tsconfig(tmp_path):
    repo = make_repo(tmp_path, {
        "package.json": json.dumps({"name": "shop", "workspaces": ["server"], "scripts": {"lint": "eslint ."}}),
        "tsconfig.json": '{\n  // base config\n  "compilerOptions": {"strict": true, "paths": {"@/*": ["src/*"]},},\n}',
        "server/package.json": json.dumps({
            "name": "@shop/server", "type": "module", "scripts": {"test": "vitest run", "dev": "tsx src"},
            "dependencies": {"express": "^5.0.1", "zod": "^3.23.8", "left-pad": "1.0.0"},
            "devDependencies": {"vitest": "^2.1.2", "@types/node": "^22", "@types/express": "^5"},
        }),
        "server/src/app.ts": "export {};\n",
        "web/package.json": json.dumps({"name": "@shop/web", "dependencies": {"react": "18.3.1"}}),
    })
    items = by_source(build_profile(repo, ["server/src/app.ts"], []))

    server = items["server/package.json"]
    assert "Express 5.0.1" in server.text and "zod 3.23.8" in server.text and "Vitest 2.1.2" in server.text
    assert "test=`vitest run`" in server.text and "dev=" not in server.text
    assert "@types/* (2)" in server.text
    assert "ancestor dir of server/src/app.ts" in server.reason
    assert "workspaces: server" in items["package.json"].text
    assert "strict=true" in items["tsconfig.json"].text and "@/*" in items["tsconfig.json"].text
    assert "web/package.json" not in items  # not on a changed path


def test_pyproject_with_ruff_config(tmp_path):
    repo = make_repo(tmp_path, {
        "pyproject.toml": """
[project]
name = "orders"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.110", "sqlalchemy[asyncio]>=2.0", "pydantic>=2"]
[project.optional-dependencies]
dev = ["pytest>=8"]
[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "B"]
ignore = ["B008"]
[tool.mypy]
strict = true
[tool.hatch.build]
include = ["app"]
""",
        "app/main.py": "",
    })
    text = by_source(build_profile(repo, ["app/main.py"], []))["pyproject.toml"].text
    assert "FastAPI 0.110" in text and "SQLAlchemy 2.0" in text and "pytest 8" in text
    assert 'tool.ruff.lint.select = ["E", "F", "B"]' in text
    assert "tool.ruff.line-length = 100" in text and "tool.mypy.strict = true" in text
    assert "hatch" not in text


def test_pom_with_spring_boot_parent_and_checkstyle(tmp_path):
    repo = make_repo(tmp_path, {
        "pom.xml": """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.4</version></parent>
  <groupId>com.acme</groupId><artifactId>inventory</artifactId>
  <properties><java.version>21</java.version></properties>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency><groupId>org.projectlombok</groupId><artifactId>lombok</artifactId></dependency>
  </dependencies>
</project>""",
        "config/checkstyle.xml": """<?xml version="1.0"?>
<module name="Checker"><module name="TreeWalker">
  <module name="LineLength"><property name="max" value="120"/></module><module name="AvoidStarImport"/>
</module></module>""",
        "src/main/java/com/acme/App.java": "class App {}\n",
    })
    items = by_source(build_profile(repo, ["src/main/java/com/acme/App.java"], []))
    pom = items["pom.xml"].text
    assert "parent: org.springframework.boot:spring-boot-starter-parent:3.3.4" in pom
    assert "java: 21" in pom
    assert "Spring Boot" in pom and "Spring Data JPA" in pom and "Lombok" in pom
    assert "LineLength(max=120)" in items["config/checkstyle.xml"].text


def test_nested_agents_md_on_changed_path_is_scoped(tmp_path):
    repo = make_repo(tmp_path, {
        "AGENTS.md": "Root rules.\n",
        "server/AGENTS.md": "Never await audit.record().\n",
        "web/AGENTS.md": "Web only.\n",
        ".cursor/rules/server.mdc": "---\nglobs:\n  - server/**/*.ts\n---\nUse zod.\n",
        ".cursor/rules/web.mdc": "---\nglobs: web/**\n---\nUse hooks.\n",
        "server/src/x.ts": "",
        "web/src/y.ts": "",
    })
    profile = build_profile(repo, ["server/src/x.ts"], [])
    items = by_source(profile)
    assert "an ancestor dir of server/src/x.ts" in items["server/AGENTS.md"].reason
    assert items["server/AGENTS.md"].priority < items["AGENTS.md"].priority  # nearer is more relevant
    assert "web/AGENTS.md" not in items
    assert "match server/src/x.ts" in items[".cursor/rules/server.mdc"].reason
    assert ".cursor/rules/web.mdc" not in items
    assert any(row["source"] == "web/AGENTS.md" and row["status"] == "skipped" for row in profile.trace())


def test_large_readme_keeps_only_relevant_sections(tmp_path):
    filler = "Lorem ipsum dolor sit amet. " * 60
    readme = "\n\n".join([
        "# Shop\n\nA shop backend.",
        f"## Deployment notes\n\n{filler}",
        f"## Error handling\n\nThrow AppError, never bare Error.\n\n{filler}",
        f"## Bookings\n\nThe booking flow must hold a lock.\n\n{filler}",
        f"## License\n\nMIT. {filler}",
    ])
    repo = make_repo(tmp_path, {"README.md": readme, "src/bookings/bookingService.ts": ""})
    profile = build_profile(repo, ["src/bookings/bookingService.ts"], [])
    items = by_source(profile)

    assert set(items) >= {"README.md#intro", "README.md#Error handling", "README.md#Bookings"}
    assert not any("License" in s or "Deployment" in s for s in items)
    assert "rule keyword 'error'" in items["README.md#Error handling"].reason
    assert "mentions booking from changed paths" in items["README.md#Bookings"].reason
    skipped = " ".join(row["reason"] for row in profile.trace() if row["status"] == "skipped")
    assert "boilerplate: License" in skipped and "Deployment notes" in skipped


def test_budget_moves_low_priority_items_to_dropped():
    items = [
        ContextItem("repo_map", "repository map", "", "m" * 400, 0),
        ContextItem("doc", "AGENTS.md", "", "a" * 400, 10),
        ContextItem("doc", "README.md", "", "r" * 4000, 40),
        ContextItem("lint_config", ".prettierrc", "", "p" * 40, 45),
    ]
    profile = fit_budget(items, budget_tokens=300)
    assert [i.source for i in profile.included] == ["repository map", "AGENTS.md", ".prettierrc"]
    assert [i.source for i in profile.dropped] == ["README.md"]
    assert {row["source"]: row["included"] for row in profile.trace()}["README.md"] is False
    assert '<context kind="doc" source="AGENTS.md">' in profile.render()


def test_malformed_files_do_not_crash(tmp_path):
    repo = make_repo(tmp_path, {
        "package.json": "{ not json",
        "pyproject.toml": "[project\nname=",
        "pom.xml": "<project>",
        "logo.png": "\0\0binary",
        "src/a.ts": "",
    })
    profile = build_profile(repo, ["src/a.ts"], [])
    assert [i.kind for i in profile.included] == ["repo_map"]


def test_excludes_apply_to_repo_map(tmp_path):
    repo = make_repo(tmp_path, {"src/a.py": "", "vendor/lib.py": "", "vendor/README.md": "vendored"})
    profile = build_profile(repo, ["src/a.py"], ["vendor/"])
    assert "vendor" not in profile.render()


def test_split_sections_ignores_code_fences_and_supports_setext():
    sections = split_sections("Title\n=====\n\nintro\n\n```sh\n# not a heading\n```\n\nUsage\n-----\n\nrun it\n")
    assert [s.headings for s in sections] == [("Title",), ("Title", "Usage")]
    assert "# not a heading" in sections[0].text


def test_path_terms_are_domain_words():
    assert path_terms(["server/src/bookings/bookingService.ts", "web/logo.png"]) == {"booking"}


def test_many_adrs_get_an_index_and_only_relevant_ones_in_full(tmp_path):
    long = "Context and consequences. " * 200
    adrs = {f"docs/adr/{i:04}-topic.md": f"# ADR {i}: Topic {i}\n\nStatus: Accepted\n\n{long}" for i in range(1, 12)}
    adrs["docs/adr/0005-topic.md"] = f"# ADR 5: Payments outbox\n\n## Status\n\nSuperseded\n\nPayments use it.\n{long}"
    repo = make_repo(tmp_path, {**adrs, "app/payments/refund.py": ""})
    items = by_source(build_profile(repo, ["app/payments/refund.py"], []))

    index = items["ADR index"].text
    assert "ADR 1: Topic 1 [Accepted]" in index and "ADR 5: Payments outbox [Superseded]" in index
    full = [s for s in items if s.startswith("docs/adr/")]
    assert full and all(s.startswith("docs/adr/0005") for s in full)
    assert "mentions payment" in items[full[0]].reason
