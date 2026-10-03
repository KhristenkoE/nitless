"""Summaries of build manifests (package.json, tsconfig, pyproject, requirements, pom.xml, Gradle).

Only manifests at the repo root and in ancestor directories of changed files are
read, so a 200-package monorepo costs the same as a single-package repo. Each
summary names the stack (frameworks, test runner, strictness flags) instead of
dumping the file.
"""

import configparser
import json
import logging
import posixpath
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nitless.context.base import ContextItem, cap_lines, parent_dir, read_text, scope_reason

log = logging.getLogger(__name__)

MAX_NAMES = 40
MAX_TOOL_LINES = 20

# dependency name -> display name; matched exactly (npm, PyPI) or as a substring (Maven artifactId)
JS_FRAMEWORKS = {
    "express": "Express", "fastify": "Fastify", "koa": "Koa", "@nestjs/core": "NestJS", "react": "React",
    "next": "Next.js", "vue": "Vue", "nuxt": "Nuxt", "@angular/core": "Angular", "svelte": "Svelte",
    "react-router-dom": "React Router", "@tanstack/react-query": "TanStack Query", "@reduxjs/toolkit": "Redux Toolkit",
    "redux": "Redux", "graphql": "GraphQL", "@apollo/server": "Apollo Server", "prisma": "Prisma",
    "@prisma/client": "Prisma", "typeorm": "TypeORM", "sequelize": "Sequelize", "mongoose": "Mongoose",
    "drizzle-orm": "Drizzle", "knex": "Knex", "zod": "zod", "yup": "yup", "joi": "Joi", "class-validator":
    "class-validator", "rxjs": "RxJS", "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
    "@playwright/test": "Playwright", "cypress": "Cypress", "@testing-library/react": "Testing Library",
    "typescript": "TypeScript", "vite": "Vite", "webpack": "webpack", "eslint": "ESLint", "prettier": "Prettier",
    "@biomejs/biome": "Biome", "tailwindcss": "Tailwind CSS",
}
PY_FRAMEWORKS = {
    "fastapi": "FastAPI", "django": "Django", "djangorestframework": "Django REST Framework", "flask": "Flask",
    "starlette": "Starlette", "aiohttp": "aiohttp", "sqlalchemy": "SQLAlchemy", "alembic": "Alembic",
    "sqlmodel": "SQLModel", "pydantic": "Pydantic", "pydantic-settings": "pydantic-settings", "celery": "Celery",
    "pytest": "pytest", "hypothesis": "Hypothesis", "mypy": "mypy", "ruff": "Ruff", "black": "Black",
    "flake8": "flake8", "pylint": "Pylint", "pandas": "pandas", "numpy": "NumPy", "httpx": "httpx",
    "requests": "requests", "structlog": "structlog", "boto3": "boto3",
}
JAVA_FRAMEWORKS = [  # (artifactId substring, name), first match per name wins
    ("spring-boot", "Spring Boot"), ("org.springframework.boot", "Spring Boot"),
    ("starter-webflux", "Spring WebFlux"), ("starter-web", "Spring MVC"),
    ("data-jpa", "Spring Data JPA"), ("hibernate", "Hibernate"), ("starter-security", "Spring Security"),
    ("starter-validation", "Bean Validation"), ("jakarta.validation", "Bean Validation"), ("lombok", "Lombok"),
    ("mapstruct", "MapStruct"), ("flyway", "Flyway"), ("liquibase", "Liquibase"), ("kafka", "Kafka"),
    ("junit-jupiter", "JUnit 5"), ("starter-test", "JUnit 5 + Mockito (spring-boot-starter-test)"),
    ("mockito", "Mockito"), ("assertj", "AssertJ"), ("testcontainers", "Testcontainers"), ("quarkus", "Quarkus"),
    ("micronaut", "Micronaut"), ("checkstyle", "Checkstyle"), ("spotbugs", "SpotBugs"), ("pmd", "PMD"),
    ("jacoco", "JaCoCo"), ("spotless", "Spotless"), ("errorprone", "Error Prone"),
]
REVIEW_TOOLS = ("ruff", "black", "isort", "mypy", "pytest", "flake8", "pylint", "pyright", "coverage", "bandit")
TS_FLAGS = (
    "extends", "strict", "noImplicitAny", "strictNullChecks", "noUncheckedIndexedAccess", "exactOptionalPropertyTypes",
    "noImplicitOverride", "noImplicitReturns", "noFallthroughCasesInSwitch", "noUnusedLocals", "noUnusedParameters",
    "useUnknownInCatchVariables", "verbatimModuleSyntax", "isolatedModules", "allowJs", "checkJs", "target",
    "module", "moduleResolution", "jsx", "baseUrl", "paths", "experimentalDecorators",
)
PY_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$")
JSONC_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|,(?=\s*[}\]])', re.S)


def manifest_items(repo: Path, files: list[str], changed: list[str]) -> list[ContextItem]:
    candidates = [p for p in files if _parser_for(posixpath.basename(p))]
    scoped = [(p, r) for p in candidates if (r := scope_reason("manifest", _scope_dir(p), changed))]
    if not scoped and candidates:  # e.g. only docs changed in a repo whose code lives in subdirs
        top = min(p.count("/") for p in candidates)
        scoped = [(p, "shallowest manifest (none at root or on changed paths)")
                  for p in candidates if p.count("/") == top][:3]
    items = []
    for i, (path, reason) in enumerate(sorted(scoped, key=lambda s: (s[0].count("/"), s[0]))):
        text = read_text(repo, path)
        if text is None:
            continue
        try:
            summary = _parser_for(posixpath.basename(path))(text)  # type: ignore[misc]
        except Exception as e:  # malformed files in an unknown repo must never fail the review
            log.debug("cannot parse %s: %s", path, e)
            continue
        if summary:
            items.append(ContextItem("manifest", path, reason, "\n".join(summary), priority=1 + min(i, 8)))
    return items


def _scope_dir(path: str) -> str:
    """The directory a manifest describes; a Gradle version catalog lives in `<project>/gradle/`."""
    folder = parent_dir(path)
    is_catalog = posixpath.basename(path) == "libs.versions.toml" and posixpath.basename(folder) == "gradle"
    return parent_dir(folder) if is_catalog else folder


def _parser_for(name: str) -> Callable[[str], list[str]] | None:
    if name == "package.json":
        return _package_json
    if name.startswith("tsconfig") and name.endswith(".json"):
        return _tsconfig
    if name == "pyproject.toml":
        return _pyproject
    if name.startswith("requirements") and name.endswith((".txt", ".in")):
        return _requirements
    if name == "setup.cfg":
        return _setup_cfg
    if name == "pom.xml":
        return _pom
    if name in ("build.gradle", "build.gradle.kts"):
        return _gradle
    if name == "libs.versions.toml":
        return _version_catalog
    return None


def loads_jsonc(text: str) -> Any:
    """json.loads that tolerates // and /* */ comments and trailing commas (tsconfig, eslintrc)."""
    return json.loads(JSONC_TOKEN_RE.sub(lambda m: m[0] if m[0].startswith('"') else "", text))


def flatten(obj: Any, prefix: str = "") -> list[str]:
    """Nested tables as `a.b = value` lines; long values are cut."""
    if isinstance(obj, dict):
        return [line for k, v in obj.items() for line in flatten(v, f"{prefix}.{k}" if prefix else str(k))]
    value = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return [f"{prefix} = {value[:160]}{'…' if len(value) > 160 else ''}"]


def _names(names: list[str]) -> str:
    """Comma list with @types/* folded, capped."""
    types = [n for n in names if n.startswith("@types/")]
    rest = [n for n in names if not n.startswith("@types/")]
    if types:
        rest.append(f"@types/* ({len(types)})")
    extra = f", … {len(rest) - MAX_NAMES} more" if len(rest) > MAX_NAMES else ""
    return ", ".join(rest[:MAX_NAMES]) + extra


def _frameworks(deps: dict[str, str], table: dict[str, str]) -> str:
    found = {}
    for dep, version in deps.items():
        name = table.get(dep.lower())
        if name and name not in found:
            found[name] = f"{name} {version.lstrip('^~=>< ')}".strip()
    return ", ".join(found.values())


def _package_json(text: str) -> list[str]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("package.json is not an object")
    deps, dev = data.get("dependencies") or {}, data.get("devDependencies") or {}
    lines = [f"name: {data.get('name', '?')}" + (f" (type: {data['type']})" if data.get("type") else "")]
    if ws := data.get("workspaces"):
        ws = ws.get("packages", []) if isinstance(ws, dict) else ws
        lines.append(f"workspaces: {', '.join(ws)}")
    scripts = {k: v for k, v in (data.get("scripts") or {}).items()
               if re.match(r"(test|lint|build|typecheck|type-check|check|format)\b", k)}
    if scripts:
        lines.append("scripts: " + "; ".join(f"{k}=`{v[:80]}{'…' * (len(v) > 80)}`" for k, v in scripts.items()))
    if engines := data.get("engines"):
        lines.append("engines: " + ", ".join(f"{k} {v}" for k, v in engines.items()))
    if stack := _frameworks({**deps, **dev}, JS_FRAMEWORKS):
        lines.append(f"frameworks/tooling: {stack}")
    if deps:
        lines.append(f"dependencies: {_names(list(deps))}")
    if dev:
        lines.append(f"devDependencies: {_names(list(dev))}")
    return lines


def _tsconfig(text: str) -> list[str]:
    data = loads_jsonc(text)
    options = {**data, **(data.get("compilerOptions") or {})}
    flags = [f"{k}={json.dumps(options[k]) if not isinstance(options[k], str) else options[k]}"
             for k in TS_FLAGS if k in options and k != "paths"]
    if "paths" in options:
        flags.append(f"path aliases: {', '.join(options['paths'])}")
    return ["compiler options: " + ", ".join(flags)] if flags else []


def _py_deps(specs: list[str]) -> dict[str, str]:
    deps = {}
    for spec in specs:
        if (m := PY_NAME_RE.match(spec.split(";")[0])) and not spec.lstrip().startswith(("-", "#")):
            deps[m[1].lower().replace("_", "-")] = m[3].strip()
    return deps


def _py_dep_lines(label: str, specs: list[str]) -> list[str]:
    deps = _py_deps(specs)
    if not deps:
        return []
    lines = [f"{label}: {_names(list(deps))}"]
    if stack := _frameworks(deps, PY_FRAMEWORKS):
        lines.append(f"  frameworks/tooling: {stack}")
    return lines


def _pyproject(text: str) -> list[str]:
    data = tomllib.loads(text)
    project, tool = data.get("project") or {}, data.get("tool") or {}
    poetry = tool.get("poetry") or {}
    lines = [f"name: {project.get('name') or poetry.get('name', '?')}"]
    if python := project.get("requires-python") or (poetry.get("dependencies") or {}).get("python"):
        lines.append(f"requires-python: {python}")
    lines += _py_dep_lines("dependencies", project.get("dependencies") or [])
    if poetry_deps := {k: v for k, v in (poetry.get("dependencies") or {}).items() if k != "python"}:
        lines += _py_dep_lines("dependencies (poetry)", list(poetry_deps))
    groups = {**(project.get("optional-dependencies") or {}), **(data.get("dependency-groups") or {})}
    for name, group in (poetry.get("group") or {}).items():
        groups[name] = list(group.get("dependencies") or {})
    for name, specs in groups.items():
        lines += _py_dep_lines(f"group {name}", [s for s in specs if isinstance(s, str)])
    for name in REVIEW_TOOLS:
        if name in tool:
            lines += cap_lines(flatten(tool[name], f"tool.{name}"), MAX_TOOL_LINES)
    return lines


def _requirements(text: str) -> list[str]:
    return _py_dep_lines("requirements", text.splitlines())


def ini_lines(text: str, sections: tuple[str, ...] | None = None) -> list[str]:
    """configparser sections as `section.key = value` lines (setup.cfg, .flake8, mypy.ini, tox.ini)."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(text)
    lines = []
    for section in parser.sections():
        if sections is None or section.split(":")[-1].split("-")[0] in sections:
            for key, value in parser[section].items():
                value = " ".join(value.split())
                lines.append(f"{section}.{key} = {value[:160]}")
    return lines


def _setup_cfg(text: str) -> list[str]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(text)
    lines = [f"name: {parser.get('metadata', 'name', fallback='?')}"]
    if python := parser.get("options", "python_requires", fallback=""):
        lines.append(f"requires-python: {python}")
    lines += _py_dep_lines("dependencies", parser.get("options", "install_requires", fallback="").splitlines())
    tools = ini_lines(text, ("flake8", "mypy", "pytest", "isort", "pycodestyle", "pylint", "coverage"))
    return lines + cap_lines(tools, MAX_TOOL_LINES)


def _java_stack(names: list[str]) -> list[str]:
    stack: list[str] = []
    for needle, name in JAVA_FRAMEWORKS:
        if name not in stack and any(needle in n for n in names):
            stack.append(name)
    return stack


def _pom(text: str) -> list[str]:
    root = ET.fromstring(text)
    for el in root.iter():
        el.tag = el.tag.rpartition("}")[2]  # drop the Maven namespace

    def get(el: ET.Element | None, path: str) -> str:
        found = el.find(path) if el is not None else None
        return (found.text or "").strip() if found is not None else ""

    lines = [f"artifact: {get(root, 'groupId') or get(root, 'parent/groupId')}:{get(root, 'artifactId')}"
             + (f" ({get(root, 'packaging')})" if get(root, "packaging") else "")]
    parent = root.find("parent")
    if parent is not None:
        lines.append(f"parent: {get(parent, 'groupId')}:{get(parent, 'artifactId')}:{get(parent, 'version')}")
    props = root.find("properties")
    java = next((get(props, k) for k in ("java.version", "maven.compiler.release", "maven.compiler.source",
                                        "maven.compiler.target") if get(props, k)), "")
    if java:
        lines.append(f"java: {java}")
    if modules := [m.text.strip() for m in root.findall("modules/module") if m.text]:
        lines.append(f"modules: {', '.join(modules)}")
    deps = [(get(d, "artifactId"), get(d, "scope")) for d in root.findall("dependencies/dependency")]
    plugins = [get(p, "artifactId") for p in root.findall("build/plugins/plugin")]
    if stack := _java_stack([get(parent, "artifactId"), *(a for a, _ in deps), *plugins]):
        lines.append(f"frameworks/tooling: {', '.join(stack)}")
    if deps:
        lines.append("dependencies: " + _names([a + (f" ({s})" if s and s != "compile" else "") for a, s in deps]))
    if plugins:
        lines.append(f"plugins: {', '.join(plugins)}")
    return lines


GRADLE_PLUGIN_RE = re.compile(
    r"""\b(?:id\s*\(?\s*["']([^"']+)["']|kotlin\s*\(\s*["']([^"']+)["']|alias\s*\(\s*libs\.plugins\.([\w.]+))"""
    r"""\s*\)?(?:\s*version\s*\(?\s*["']([^"']+))?""")
GRADLE_DEP_RE = re.compile(
    r"""\b(implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|annotationProcessor|kapt|ksp)"""
    r"""\s*\(?\s*(?:platform\()?(?:["'][^:"']+:([^:"']+)|libs\.([\w.]+))"""
)
GRADLE_JAVA_RE = re.compile(r"JavaLanguageVersion\.of\((\d+)\)|(?:source|target)Compatibility\s*=\s*"
                            r"(?:JavaVersion\.VERSION_)?['\"]?([\d._]+)")


def _gradle(text: str) -> list[str]:
    plugins = [(pid or (f"kotlin-{kotlin}" if kotlin else alias)) + (f" {v}" if v else "")
               for pid, kotlin, alias, v in GRADLE_PLUGIN_RE.findall(text)]
    deps = [(artifact or f"libs.{alias}") + (" (test)" if conf.startswith("test") else "")
            for conf, artifact, alias in GRADLE_DEP_RE.findall(text)]
    lines = []
    if m := GRADLE_JAVA_RE.search(text):
        lines.append(f"java: {m[1] or m[2]}")
    if stack := _java_stack(plugins + deps):
        lines.append(f"frameworks/tooling: {', '.join(stack)}")
    if plugins:
        lines.append(f"plugins: {', '.join(plugins)}")
    if deps:
        lines.append(f"dependencies: {_names(deps)}")
    return lines


def _version_catalog(text: str) -> list[str]:
    data = tomllib.loads(text)
    libraries = []
    for lib in (data.get("libraries") or {}).values():
        module = lib if isinstance(lib, str) else lib.get("module") or f"{lib.get('group')}:{lib.get('name')}"
        libraries.append(module.split(":")[1] if module.count(":") >= 1 else module)
    plugins = [p if isinstance(p, str) else p.get("id", "?") for p in (data.get("plugins") or {}).values()]
    lines = []
    if stack := _java_stack(libraries + plugins):
        lines.append(f"frameworks/tooling: {', '.join(stack)}")
    if plugins:
        lines.append(f"plugins: {_names(plugins)}")
    if libraries:
        lines.append(f"libraries: {_names(libraries)}")
    return lines
