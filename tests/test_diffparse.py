from changerisk.diffparse import parse_diff, unquote
from changerisk.models import ADDED, DELETED, MODIFIED, RENAMED

MODIFIED_DIFF = """\
diff --git a/app/server.py b/app/server.py
index 1111111..2222222 100644
--- a/app/server.py
+++ b/app/server.py
@@ -10,7 +10,8 @@ def serve():
     host = "0.0.0.0"
-    port = 8000
+    port = 9000
+    workers = 4
     run(host, port)
@@ -40,3 +41,2 @@ class Server:
     def stop(self):
-        self.sock.close()
         return None
"""


def test_modified_file_with_two_hunks():
    (fc,) = parse_diff(MODIFIED_DIFF)
    assert fc.path == "app/server.py"
    assert fc.status == MODIFIED
    assert (fc.additions, fc.deletions) == (2, 2)
    assert len(fc.hunks) == 2
    first = fc.hunks[0]
    assert first.header == "def serve():"
    assert [(x.kind, x.old_no, x.new_no) for x in first.lines] == [
        (" ", 10, 10),
        ("-", 11, None),
        ("+", None, 11),
        ("+", None, 12),
        (" ", 12, 13),
    ]
    assert [x.text for x in fc.added_lines()] == ["    port = 9000", "    workers = 4"]


def test_added_and_deleted_files():
    diff = """\
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+one
+two
diff --git a/old.txt b/old.txt
deleted file mode 100644
index e69de29..0000000
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""
    added, deleted = parse_diff(diff)
    assert (added.path, added.status, added.additions) == ("new.txt", ADDED, 2)
    assert (deleted.path, deleted.status, deleted.deletions) == ("old.txt", DELETED, 1)


def test_rename_with_edits_keeps_both_paths():
    diff = """\
diff --git a/src/a.py b/src/b.py
similarity index 80%
rename from src/a.py
rename to src/b.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/b.py
@@ -1,2 +1,2 @@
 keep
-old
+new
"""
    (fc,) = parse_diff(diff)
    assert fc.status == RENAMED
    assert (fc.old_path, fc.path, fc.similarity) == ("src/a.py", "src/b.py", 80)
    assert fc.changed_lines == 2


def test_pure_rename_has_no_hunks():
    diff = """\
diff --git a/x.txt b/y.txt
similarity index 100%
rename from x.txt
rename to y.txt
"""
    (fc,) = parse_diff(diff)
    assert fc.status == RENAMED
    assert fc.hunks == []
    assert fc.changed_lines == 0


def test_binary_file_is_flagged():
    diff = """\
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..abcdef0
Binary files /dev/null and b/logo.png differ
"""
    (fc,) = parse_diff(diff)
    assert fc.binary and fc.status == ADDED and fc.path == "logo.png"


def test_mode_change_only():
    diff = """\
diff --git a/run.sh b/run.sh
old mode 100644
new mode 100755
"""
    (fc,) = parse_diff(diff)
    assert fc.mode_change == ("100644", "100755")
    assert fc.changed_lines == 0


def test_paths_with_spaces_use_the_tab_terminated_headers():
    diff = (
        "diff --git a/my notes.txt b/my notes.txt\n"
        "index 1..2 100644\n"
        "--- a/my notes.txt\t\n"
        "+++ b/my notes.txt\t\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    (fc,) = parse_diff(diff)
    assert fc.path == "my notes.txt"


def test_quoted_path_with_escapes_and_octal():
    assert unquote('"caf\\303\\251.txt"') == "café.txt"
    assert unquote('"tab\\there"') == "tab\there"
    assert unquote("plain") == "plain"


def test_no_newline_marker_is_ignored_and_does_not_shift_numbers():
    diff = """\
diff --git a/f.txt b/f.txt
index 1..2 100644
--- a/f.txt
+++ b/f.txt
@@ -1,2 +1,2 @@
 first
-last
\\ No newline at end of file
+last!
\\ No newline at end of file
"""
    (fc,) = parse_diff(diff)
    kinds = [(x.kind, x.text) for x in fc.hunks[0].lines]
    assert kinds == [(" ", "first"), ("-", "last"), ("+", "last!")]


def test_crlf_is_stripped_from_line_text():
    diff = "diff --git a/w.txt b/w.txt\n--- a/w.txt\n+++ b/w.txt\n@@ -1 +1 @@\n-old\r\n+new\r\n"
    (fc,) = parse_diff(diff)
    assert [x.text for x in fc.added_lines()] == ["new"]


def test_deleted_line_that_looks_like_a_header_stays_a_deletion():
    diff = """\
diff --git a/f.md b/f.md
index 1..2 100644
--- a/f.md
+++ b/f.md
@@ -1,3 +1,2 @@
 title
--- not a header
+++ also not a header
"""
    (fc,) = parse_diff(diff)
    assert (fc.deletions, fc.additions) == (1, 1)
    assert fc.path == "f.md"


def test_empty_input():
    assert parse_diff("") == []


def test_quoted_header_for_a_name_with_special_characters():
    diff = (
        'diff --git "a/caf\\303\\251 \\"menu\\".txt" "b/caf\\303\\251 \\"menu\\".txt"\n'
        "index 1..2 100644\n"
        '--- "a/caf\\303\\251 \\"menu\\".txt"\n'
        '+++ "b/caf\\303\\251 \\"menu\\".txt"\n'
        "@@ -1 +1 @@\n-a\n+b\n"
    )
    (fc,) = parse_diff(diff)
    assert fc.path == 'caf\u00e9 "menu".txt'
    assert (fc.additions, fc.deletions) == (1, 1)


def test_rename_between_names_with_spaces_uses_the_rename_lines():
    diff = (
        "diff --git a/old name.txt b/new name.txt\n"
        "similarity index 100%\n"
        "rename from old name.txt\n"
        "rename to new name.txt\n"
    )
    (fc,) = parse_diff(diff)
    assert (fc.old_path, fc.path, fc.status) == ("old name.txt", "new name.txt", RENAMED)


def test_copy_and_typechange_and_binary_delete():
    diff = (
        "diff --git a/src.txt b/dup.txt\n"
        "similarity index 100%\n"
        "copy from src.txt\n"
        "copy to dup.txt\n"
        "diff --git a/link b/link\n"
        "old mode 120000\n"
        "new mode 100644\n"
        "diff --git a/img.png b/img.png\n"
        "deleted file mode 100644\n"
        "Binary files a/img.png and /dev/null differ\n"
    )
    copied, changed, binary = parse_diff(diff)
    assert (copied.status, copied.old_path, copied.path) == ("copied", "src.txt", "dup.txt")
    assert changed.status == "typechange" and changed.mode_change == ("120000", "100644")
    assert (binary.status, binary.binary, binary.path) == (DELETED, True, "img.png")


def test_unterminated_quote_does_not_crash():
    (fc,) = parse_diff('diff --git "a/broken b/broken\n')
    assert fc.path == "?"
