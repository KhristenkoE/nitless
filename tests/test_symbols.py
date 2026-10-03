from nitless.context.changes import changed_symbols
from nitless.context.symbols import Import, parse

PY = '''\
from app.core.money import Money as M
from . import repo

class OrderService:
    """Creates orders."""

    def __init__(self, repo):
        self.repo = repo

    @transactional
    def create_order(self, items: list,
                     coupon=None) -> M:
        total = self.repo.total(items)
        return M(total)

def helper():
    def inner():
        pass
    return inner
'''


def by_qualname(source):
    return {d.qualname: d for d in source.definitions}


def test_python_definitions_and_imports():
    src = parse("app/services/orders.py", PY)
    defs = by_qualname(src)
    assert set(defs) == {"OrderService", "OrderService.__init__", "OrderService.create_order", "helper",
                         "helper.inner"}
    create = defs["OrderService.create_order"]
    assert create.kind == "method" and defs["helper.inner"].kind == "function"
    assert (create.start, create.line, create.header_end, create.end) == (10, 10, 12, 14)  # decorator included
    assert create.signature == "@transactional def create_order(self, items: list, coupon=None) -> M:"
    assert src.enclosing(13).qualname == "OrderService.create_order"
    assert src.members(defs["OrderService"]) == [defs["OrderService.__init__"], create]
    assert src.imports == [Import("app.core.money", "Money", "M", 1), Import(".", "repo", "repo", 2)]
    assert src.import_block == (1, 2)
    refs = {(r.name, r.receiver) for r in src.references(13, 14)}
    assert ("total", "self.repo") in refs and ("M", None) in refs


TS = '''\
import express, { Router as R } from "express";
import * as audit from "../lib/audit.js";

/** Lists rooms. */
export async function listRooms(repo: Repo, page = 1): Promise<Room[]> {
  return repo.find({ page });
}

export const toDto = (room: Room) => ({ id: room.id });

export interface Room { id: string }

export class RoomService {
  constructor(private repo: Repo) {}
  rename(id: string, name: string) {
    audit.record("rename", id);
  }
}
'''


def test_typescript_definitions_and_imports():
    src = parse("server/src/rooms.ts", TS)
    defs = by_qualname(src)
    assert {q: d.kind for q, d in defs.items()} == {
        "listRooms": "function", "toDto": "function", "Room": "interface", "RoomService": "class",
        "RoomService.constructor": "method", "RoomService.rename": "method"}
    assert defs["listRooms"].start == 4  # JSDoc belongs to the function
    assert defs["listRooms"].signature.startswith("export async function listRooms(repo: Repo, page = 1)")
    assert src.imports == [Import("express", "default", "express", 1), Import("express", "Router", "R", 1),
                           Import("../lib/audit.js", None, "audit", 2)]
    assert ("record", "audit") in {(r.name, r.receiver) for r in src.references(16, 16)}


JAVA = '''\
package com.acme.inventory.service;

import static com.acme.common.Checks.requirePositive;
import com.acme.inventory.domain.*;
import com.acme.inventory.repository.StockLevelRepository;

/**
 * Records stock movements.
 */
@Service
public class StockLedger {
    private final StockLevelRepository levels;

    public StockLedger(StockLevelRepository levels) {
        this.levels = levels;
    }

    public StockLevel record(String sku, int quantity) {
        requirePositive(quantity);
        return levels.lock(sku).add(quantity);
    }

    public record Movement(String sku, int quantity) {}
}
'''


def test_java_definitions_and_imports():
    src = parse("src/main/java/com/acme/inventory/service/StockLedger.java", JAVA)
    defs = by_qualname(src)
    assert {q: d.kind for q, d in defs.items()} == {
        "StockLedger": "class", "StockLedger.StockLedger": "method", "StockLedger.record": "method",
        "StockLedger.Movement": "record"}
    assert defs["StockLedger"].start == 7  # Javadoc and annotation included
    assert defs["StockLedger.record"].signature == "public StockLevel record(String sku, int quantity)"
    assert src.imports == [
        Import("com.acme.common.Checks", "requirePositive", "requirePositive", 3),
        Import("com.acme.inventory.domain", "*", "", 4),
        Import("com.acme.inventory.repository.StockLevelRepository", "StockLevelRepository",
               "StockLevelRepository", 5)]
    assert src.import_block == (1, 5)
    assert ("lock", "levels") in {(r.name, r.receiver) for r in src.references(20, 20)}


def test_unknown_language_falls_back_to_regex():
    src = parse("cmd/main.go", "package main\n\nfunc main() {\n\trun()\n}\n\nfunc run() {}\n")
    assert [(d.name, d.start, d.end) for d in src.definitions] == [("main", 3, 5), ("run", 7, 7)]
    assert src.language is None and "run" in {r.name for r in src.references(4, 4)}


def test_changed_symbols_classify_added_modified_signature_removed():
    old = parse("m.py", "def keep(a):\n    return a\n\ndef grow(a):\n    return a\n\ndef gone():\n    pass\n")
    new = parse("m.py", "def keep(a):\n    return a + 1\n\ndef grow(a, b=0):\n    return a\n\n"
                        "def fresh():\n    pass\n")
    symbols = changed_symbols("m.py", new, old, touched={2, 4, 7, 8}, removed={4, 7, 8})
    changes = {s.definition.qualname: (s.change, s.breaking) for s in symbols}
    assert changes == {"keep": ("modified", False), "grow": ("signature", True), "fresh": ("added", False),
                       "gone": ("removed", True)}
    grow = next(s for s in symbols if s.change == "signature")
    assert grow.describe() == "grow (signature changed from `def grow(a):`)"


def test_class_is_not_changed_when_only_its_members_are():
    text = "class A:\n    x = 1\n\n    def f(self):\n        return 1\n"
    old, new = parse("a.py", text), parse("a.py", text.replace("return 1", "return 2"))
    assert [s.definition.qualname for s in changed_symbols("a.py", new, old, {5}, {5})] == ["A.f"]
    assert {s.definition.qualname for s in changed_symbols("a.py", new, old, {2, 5}, set())} == {"A", "A.f"}
