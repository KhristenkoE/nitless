from nitless.diff import filter_excluded, parse_diff, render_for_llm

DIFF = """\
diff --git a/app/users.py b/app/users.py
index 1111111..2222222 100644
--- a/app/users.py
+++ b/app/users.py
@@ -10,4 +10,5 @@ def get_user(email):
     user = db.find(email)
-    if user is None:
-        return None
+    if not user:
+        raise NotFound(email)
+    log.info("found")
     return user
diff --git a/schema.sql b/schema.sql
--- a/schema.sql
+++ b/schema.sql
@@ -1,2 +1,1 @@
--- legacy column
 CREATE TABLE t (id int);
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
\\ No newline at end of file
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone = True
diff --git a/a b/b
similarity index 100%
rename from src/a name.py
rename to src/b name.py
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
"""


def test_parses_files_and_statuses():
    files = parse_diff(DIFF)
    assert [(f.path, f.status) for f in files] == [
        ("app/users.py", "modified"),
        ("schema.sql", "modified"),
        ("new.py", "added"),
        ("old.py", "deleted"),
        ("src/b name.py", "renamed"),
        ("logo.png", "modified"),
    ]
    assert files[4].old_path == "src/a name.py"
    assert files[5].is_binary


def test_line_numbers_follow_both_sides():
    users = parse_diff(DIFF)[0]
    added = [(ln.new_no, ln.text.strip()) for ln in users.hunks[0].lines if ln.kind == "+"]
    assert added == [(11, "if not user:"), (12, "raise NotFound(email)"), (13, 'log.info("found")')]
    removed = [ln.old_no for ln in users.hunks[0].lines if ln.kind == "-"]
    assert removed == [11, 12]
    assert users.added == 3 and users.removed == 2
    assert users.covers_line(12) and not users.covers_line(30)


def test_removed_line_that_looks_like_a_header_is_content():
    sql = parse_diff(DIFF)[1]
    assert sql.old_path == "schema.sql" and sql.removed == 1
    assert sql.hunks[0].lines[0].text == "-- legacy column"


def test_no_newline_marker_is_ignored():
    new = parse_diff(DIFF)[2]
    assert [ln.text for ln in new.hunks[0].lines] == ["x = 1", "y = 2"]


def test_filter_excluded_skips_binaries_and_patterns():
    kept, skipped = filter_excluded(parse_diff(DIFF), ["*.sql", "old.py"])
    assert {f.path for f in kept} == {"app/users.py", "new.py", "src/b name.py"}
    assert set(skipped) == {"schema.sql", "old.py", "logo.png"}


def test_render_shows_new_line_numbers():
    rendered = render_for_llm(parse_diff(DIFF)[:1])
    assert "    12 +         raise NotFound(email)" in rendered
    assert "       -     if user is None:" in rendered
