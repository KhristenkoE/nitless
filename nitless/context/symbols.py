"""Definitions, references and imports of one source file.

tree-sitter parses Python, JavaScript/JSX, TypeScript/TSX and Java; any other language gets
regex heuristics, which are good enough to find a definition and cut a snippet around it.
Line numbers are 1-based and inclusive everywhere.
"""

import logging
import posixpath
import re
import threading
from dataclasses import dataclass, field
from functools import cache

import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

log = logging.getLogger(__name__)

LANGUAGES = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx",
    ".java": "java",
}
GRAMMARS = {
    "python": tree_sitter_python.language,
    "javascript": tree_sitter_javascript.language,
    "typescript": tree_sitter_typescript.language_typescript,
    "tsx": tree_sitter_typescript.language_tsx,
    "java": tree_sitter_java.language,
}
DEF_KINDS = {
    "function_definition": "function", "class_definition": "class",  # python
    "function_declaration": "function", "generator_function_declaration": "function",  # js/ts
    "class_declaration": "class", "abstract_class_declaration": "class", "method_definition": "method",
    "interface_declaration": "interface", "enum_declaration": "enum", "type_alias_declaration": "type",
    "method_declaration": "method", "constructor_declaration": "method", "record_declaration": "record",  # java
    "annotation_type_declaration": "interface",
}
CLASS_KINDS = {"class", "interface", "enum", "record"}
FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}
IDENTIFIERS = {"identifier", "property_identifier", "type_identifier", "field_identifier",
               "shorthand_property_identifier", "shorthand_property_identifier_pattern"}
MEMBER_ACCESS = {"attribute": ("object", "attribute"), "member_expression": ("object", "property"),
                 "method_invocation": ("object", "name"), "field_access": ("object", "field")}
WRAPPERS = {"decorated_definition", "export_statement"}  # their range belongs to the definition they wrap
MAX_RECEIVER_CHARS = 60

FALLBACK_DEF_RE = re.compile(
    r"^(\s*)(?:export\s+)?(?:(?:public|private|protected|static|async|abstract|final|pub)\s+)*"
    r"(def|function|class|interface|func|fn|struct|trait|enum|module|object)\s+([A-Za-z_$][\w$]*)"
)
WORD_RE = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass(frozen=True)
class Definition:
    name: str
    kind: str  # function | method | class | interface | enum | type | record | variable
    qualname: str  # "OrderService.create_order"
    start: int  # first line, including leading doc comments and decorators/annotations
    line: int  # line of the declaration itself
    header_end: int  # last line of the signature (before the body)
    end: int
    signature: str  # whitespace-normalized header, compared across base and head

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end


@dataclass(frozen=True)
class Ref:
    name: str
    receiver: str | None  # "bookingRepository" in bookingRepository.listForRoom(...)
    line: int


@dataclass(frozen=True)
class Import:
    module: str  # "app.core.money", "../lib/audit.js", "com.acme.inventory.service.StockLedger"
    name: str | None  # imported member; None for a module/namespace import
    alias: str  # the local name it is bound to
    line: int


@dataclass
class SourceFile:
    path: str
    language: str | None  # None: regex fallback
    lines: list[str]
    definitions: list[Definition] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    import_block: tuple[int, int] | None = None
    blocks: list[tuple[int, int]] = field(default_factory=list)  # top-level statements
    tree: object = None  # tree_sitter.Tree

    def enclosing(self, line: int, kinds: set[str] | None = None) -> Definition | None:
        """Innermost definition containing `line` (optionally of the given kinds)."""
        hits = [d for d in self.definitions if d.contains(line) and (kinds is None or d.kind in kinds)]
        return min(hits, key=lambda d: d.size, default=None)

    def named(self, name: str) -> list[Definition]:
        return [d for d in self.definitions if d.name == name]

    def members(self, parent: Definition) -> list[Definition]:
        prefix = parent.qualname + "."
        return [d for d in self.definitions if d.qualname.startswith(prefix) and "." not in d.qualname[len(prefix):]]

    def references(self, start: int, end: int) -> list[Ref]:
        if self.tree is None:
            return [Ref(m[0], None, n) for n in range(start, min(end, len(self.lines)) + 1)
                    for m in WORD_RE.finditer(self.lines[n - 1])]
        refs: list[Ref] = []
        _collect_refs(self.tree.root_node, start - 1, end - 1, refs)
        return refs


def language_of(path: str) -> str | None:
    return LANGUAGES.get(posixpath.splitext(path)[1].lower())


_threads = threading.local()  # a tree-sitter Parser must not be shared between threads


@cache
def _language(language: str) -> Language:
    return Language(GRAMMARS[language]())


def _parser(language: str) -> Parser:
    parsers = _threads.__dict__.setdefault("parsers", {})
    if language not in parsers:
        parsers[language] = Parser(_language(language))
    return parsers[language]


def parse(path: str, text: str) -> SourceFile:
    language = language_of(path)
    lines = text.splitlines()
    if language is None:
        return SourceFile(path, None, lines, definitions=_fallback_definitions(lines))
    try:
        tree = _parser(language).parse(text.encode())
    except Exception as e:  # noqa: BLE001 - a parser failure must never break a review
        log.debug("cannot parse %s: %s", path, e)
        return SourceFile(path, None, lines, definitions=_fallback_definitions(lines))
    source = SourceFile(path, language, lines, tree=tree)
    root = tree.root_node
    _collect_definitions(root, [], source.definitions)
    source.imports = _imports(root, language)
    import_lines = [n.start_point.row + 1 for n in root.children if _is_import(n, language)]
    if import_lines:
        source.import_block = (min(import_lines), max(n.end_point.row + 1 for n in root.children
                                                          if _is_import(n, language)))
    source.blocks = [(_doc_start(n), n.end_point.row + 1) for n in root.named_children if n.type != "comment"]
    return source


# --- definitions ------------------------------------------------------------------------------


def _collect_definitions(node: Node, scope: list[str], out: list[Definition], in_class: bool = False) -> None:
    for child in node.named_children:
        definition = _definition(child, scope, in_class)
        if definition is None:
            if child.type in WRAPPERS:
                _collect_definitions(child, scope, out, in_class)
            continue
        out.append(definition)
        body = _unwrap(child).child_by_field_name("body")
        if body is not None and definition.kind != "variable":
            _collect_definitions(body, [*scope, definition.name], out, definition.kind in CLASS_KINDS)


def _unwrap(node: Node) -> Node:
    """The definition inside decorator/export wrappers."""
    while node.type in WRAPPERS:
        inner = node.child_by_field_name("definition") or node.child_by_field_name("declaration")
        if inner is None:
            inner = next((c for c in node.named_children if c.type != "decorator"), None)
        if inner is None:
            return node
        node = inner
    return node


def _definition(node: Node, scope: list[str], in_class: bool) -> Definition | None:
    outer, inner = node, _unwrap(node)
    kind = DEF_KINDS.get(inner.type)
    target, body = inner, inner.child_by_field_name("body")
    if kind is None and inner.type in ("lexical_declaration", "variable_declaration") and not scope:
        declarator = next((c for c in inner.named_children if c.type == "variable_declarator"), None)
        if declarator is None:
            return None
        value = declarator.child_by_field_name("value")
        kind = "function" if value is not None and value.type in FUNCTION_VALUES else "variable"
        target = declarator
        body = value.child_by_field_name("body") if kind == "function" else value
    if kind is None:
        return None
    name_node = target.child_by_field_name("name")
    if name_node is None or name_node.type not in IDENTIFIERS:
        return None
    name = name_node.text.decode()
    if kind == "function" and in_class:
        kind = "method"
    line = outer.start_point.row + 1
    # A Python block starts at its first statement, so the header ends at the token before the body (the colon).
    header = body.prev_sibling if body is not None and kind != "variable" else None
    header_end = header.end_point.row + 1 if header is not None else outer.end_point.row + 1
    header_end = max(line, min(header_end, outer.end_point.row + 1))
    header_stop = body.start_byte if body is not None and kind != "variable" else outer.end_byte
    signature = " ".join(outer.text[: header_stop - outer.start_byte].decode(errors="replace").split())
    return Definition(name=name, kind=kind, qualname=".".join([*scope, name]), start=_doc_start(outer),
                      line=line, header_end=header_end, end=outer.end_point.row + 1, signature=signature)


def _doc_start(node: Node) -> int:
    """First line of the node, extended upwards over directly preceding comments (Javadoc, JSDoc)."""
    start = node.start_point.row
    prev = node.prev_sibling
    while prev is not None and prev.type in ("comment", "block_comment", "line_comment") \
            and prev.end_point.row >= start - 1:
        start = prev.start_point.row
        prev = prev.prev_sibling
    return start + 1


def _fallback_definitions(lines: list[str]) -> list[Definition]:
    found = [(i, len(m[1]), m[2], m[3]) for i, text in enumerate(lines, 1) if (m := FALLBACK_DEF_RE.match(text))]
    out = []
    for n, (line, indent, keyword, name) in enumerate(found):
        end = len(lines)
        for next_line, next_indent, _, _ in found[n + 1:]:
            if next_indent <= indent:
                end = next_line - 1
                break
        while end > line and not lines[end - 1].strip():
            end -= 1
        kind = "class" if keyword in ("class", "interface", "struct", "trait", "enum", "module", "object") \
            else "function"
        out.append(Definition(name, kind, name, line, line, line, end, " ".join(lines[line - 1].split())))
    return out


# --- references -------------------------------------------------------------------------------


def _collect_refs(node: Node, first: int, last: int, out: list[Ref]) -> None:
    if node.end_point.row < first or node.start_point.row > last:
        return
    fields = MEMBER_ACCESS.get(node.type)
    if fields is not None:
        obj, member = node.child_by_field_name(fields[0]), node.child_by_field_name(fields[1])
        if member is not None and first <= member.start_point.row <= last:
            text = _text(obj)
            receiver = text if text and len(text) <= MAX_RECEIVER_CHARS and "\n" not in text else None
            out.append(Ref(_text(member), receiver, member.start_point.row + 1))
        if obj is not None:
            _collect_refs(obj, first, last, out)
        for child in node.children:
            if child not in (obj, member):
                _collect_refs(child, first, last, out)
        return
    if node.type in IDENTIFIERS and node.child_count == 0:
        if first <= node.start_point.row <= last:
            out.append(Ref(node.text.decode(errors="replace"), None, node.start_point.row + 1))
        return
    for child in node.children:
        _collect_refs(child, first, last, out)


# --- imports ----------------------------------------------------------------------------------


def _is_import(node: Node, language: str) -> bool:
    if language == "python":
        return node.type in ("import_statement", "import_from_statement", "future_import_statement")
    if language == "java":
        return node.type in ("import_declaration", "package_declaration")
    return node.type == "import_statement"


def _imports(root: Node, language: str) -> list[Import]:
    out: list[Import] = []
    for node in root.children:
        if not _is_import(node, language):
            continue
        line = node.start_point.row + 1
        try:
            out.extend(IMPORT_PARSERS[language](node, line))
        except (AttributeError, IndexError) as e:
            log.debug("unparsed import on line %d: %s", line, e)
    return out


def _text(node: Node | None) -> str:
    return node.text.decode(errors="replace") if node is not None else ""


def _python_imports(node: Node, line: int) -> list[Import]:
    if node.type == "import_statement":
        out = []
        for child in node.named_children:
            if child.type == "aliased_import":
                out.append(Import(_text(child.child_by_field_name("name")), None,
                                  _text(child.child_by_field_name("alias")), line))
            elif child.type == "dotted_name":
                out.append(Import(_text(child), None, _text(child), line))
        return out
    if node.type != "import_from_statement":
        return []
    module = _text(node.child_by_field_name("module_name"))
    out = []
    for child in node.children_by_field_name("name"):
        if child.type == "aliased_import":
            out.append(Import(module, _text(child.child_by_field_name("name")),
                              _text(child.child_by_field_name("alias")), line))
        else:
            out.append(Import(module, _text(child), _text(child).rsplit(".", 1)[-1], line))
    return out


def _js_imports(node: Node, line: int) -> list[Import]:
    source = node.child_by_field_name("source")
    module = _text(source).strip("'\"`")
    clause = next((c for c in node.named_children if c.type == "import_clause"), None)
    if clause is None:
        return [Import(module, None, "", line)]  # side-effect import
    out = []
    for child in clause.named_children:
        if child.type == "identifier":
            out.append(Import(module, "default", _text(child), line))
        elif child.type == "namespace_import":
            alias = next((c for c in child.named_children if c.type == "identifier"), None)
            out.append(Import(module, None, _text(alias), line))
        elif child.type == "named_imports":
            for spec in child.named_children:
                if spec.type == "import_specifier":
                    name = _text(spec.child_by_field_name("name"))
                    out.append(Import(module, name, _text(spec.child_by_field_name("alias")) or name, line))
    return out


def _java_imports(node: Node, line: int) -> list[Import]:
    if node.type != "import_declaration":
        return []
    path = _text(next(c for c in node.named_children if c.type in ("scoped_identifier", "identifier")))
    wildcard = any(c.type == "asterisk" for c in node.children)
    if wildcard:
        return [Import(path, "*", "", line)]
    owner, _, name = path.rpartition(".")
    is_static = any(c.type == "static" for c in node.children)
    return [Import(owner if is_static else path, name, name, line)]


IMPORT_PARSERS = {"python": _python_imports, "javascript": _js_imports, "typescript": _js_imports,
                  "tsx": _js_imports, "java": _java_imports}
