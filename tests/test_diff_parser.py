"""Tests for the unified diff parser module."""

from __future__ import annotations

import pytest

from ai_code_reviewer.diff_parser import (
    extract_changed_lines,
    parse_hunk_header,
    parse_unified_diff,
)

SAMPLE_DIFF = """\
diff --git a/app.py b/app.py
index abc1234..def5678 100644
--- a/app.py
+++ b/app.py
@@ -10,6 +10,8 @@ class App:
     def __init__(self):
         self.name = "test"
+        self.version = "1.0"
+        self.debug = False
 
     def run(self):
         pass
@@ -25,3 +27,4 @@ class App:
     def stop(self):
         pass
+        self.cleanup()
"""

MULTI_FILE_DIFF = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 import os
+import sys
 
 def main():
diff --git a/utils.py b/utils.py
new file mode 100644
--- /dev/null
+++ b/utils.py
@@ -0,0 +1,5 @@
+def helper():
+    return True
+
+def other():
+    return False
"""


class TestParseUnifiedDiff:
    def test_single_file_diff(self) -> None:
        files = parse_unified_diff(SAMPLE_DIFF)
        assert len(files) == 1
        assert files[0].filename == "app.py"
        assert files[0].status == "modified"
        assert files[0].additions == 3
        assert files[0].deletions == 0

    def test_multi_file_diff(self) -> None:
        files = parse_unified_diff(MULTI_FILE_DIFF)
        assert len(files) == 2
        assert files[0].filename == "app.py"
        assert files[1].filename == "utils.py"
        assert files[1].status == "added"
        assert files[1].additions == 5

    def test_empty_diff(self) -> None:
        assert parse_unified_diff("") == []
        assert parse_unified_diff("   \n  ") == []

    def test_hunks_are_parsed(self) -> None:
        files = parse_unified_diff(SAMPLE_DIFF)
        assert len(files[0].hunks) == 2
        assert files[0].hunks[0].old_start == 10
        assert files[0].hunks[0].new_start == 10
        assert files[0].hunks[1].old_start == 25

    def test_binary_file(self) -> None:
        diff = """\
diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ
"""
        files = parse_unified_diff(diff)
        assert len(files) == 1
        assert files[0].filename == "image.png"

    def test_renamed_file(self) -> None:
        diff = """\
diff --git a/old.py b/new.py
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1,2 +1,2 @@
-old_name = True
+new_name = True
"""
        files = parse_unified_diff(diff)
        assert len(files) == 1
        assert files[0].status == "renamed"
        assert files[0].filename == "new.py"


class TestParseHunkHeader:
    def test_standard_hunk(self) -> None:
        hunk = parse_hunk_header("@@ -10,6 +10,8 @@ class App:")
        assert hunk is not None
        assert hunk.old_start == 10
        assert hunk.old_count == 6
        assert hunk.new_start == 10
        assert hunk.new_count == 8
        assert hunk.header == "class App:"

    def test_single_line_hunk(self) -> None:
        hunk = parse_hunk_header("@@ -1 +1,2 @@")
        assert hunk is not None
        assert hunk.old_start == 1
        assert hunk.old_count == 1
        assert hunk.new_count == 2

    def test_creation_hunk(self) -> None:
        hunk = parse_hunk_header("@@ -0,0 +1,5 @@")
        assert hunk is not None
        assert hunk.old_start == 0
        assert hunk.new_start == 1
        assert hunk.new_count == 5

    def test_invalid_header_returns_none(self) -> None:
        assert parse_hunk_header("not a hunk header") is None
        assert parse_hunk_header("") is None


class TestExtractChangedLines:
    def test_extracts_additions(self) -> None:
        patch = "@@ -1,3 +1,5 @@\n context\n+added line 1\n+added line 2\n context"
        changed = extract_changed_lines(patch)
        assert len(changed) == 2
        assert changed[0] == (2, "added line 1")
        assert changed[1] == (3, "added line 2")

    def test_skips_deletions(self) -> None:
        patch = "@@ -1,3 +1,2 @@\n context\n-deleted line\n context"
        changed = extract_changed_lines(patch)
        assert len(changed) == 0

    def test_multiple_hunks(self) -> None:
        patch = (
            "@@ -1,2 +1,3 @@\n context\n+line A\n context\n"
            "@@ -10,2 +11,3 @@\n context\n+line B\n context"
        )
        changed = extract_changed_lines(patch)
        assert len(changed) == 2
        assert changed[0][1] == "line A"
        assert changed[1][1] == "line B"

    def test_empty_patch(self) -> None:
        assert extract_changed_lines("") == []
