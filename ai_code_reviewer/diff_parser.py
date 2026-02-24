"""Parser for unified diff format used by Git and GitHub.

Converts raw unified diff text into structured FileChange and DiffHunk
models suitable for analysis by the review engine.
"""

from __future__ import annotations

import re

from ai_code_reviewer.logging_config import get_logger
from ai_code_reviewer.models import DiffHunk, FileChange

logger = get_logger(__name__)

HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)
DIFF_FILE_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")
BINARY_FILE_RE = re.compile(r"^Binary files .* differ$")


def parse_unified_diff(diff_text: str) -> list[FileChange]:
    """Parse a full unified diff into a list of file changes.

    Handles multi-file diffs as produced by ``git diff`` or the GitHub API.
    Each file section is parsed into a FileChange with its associated hunks.

    Args:
        diff_text: Raw unified diff text, potentially containing
                   multiple file sections.

    Returns:
        List of parsed file changes.
    """
    if not diff_text.strip():
        return []

    files: list[FileChange] = []
    current_filename: str | None = None
    current_patch_lines: list[str] = []
    current_hunks: list[DiffHunk] = []
    additions = 0
    deletions = 0
    status = "modified"

    for line in diff_text.split("\n"):
        file_match = DIFF_FILE_HEADER_RE.match(line)
        if file_match:
            if current_filename is not None:
                files.append(
                    _build_file_change(
                        current_filename,
                        status,
                        current_patch_lines,
                        current_hunks,
                        additions,
                        deletions,
                    )
                )
            current_filename = file_match.group(2)
            current_patch_lines = []
            current_hunks = []
            additions = 0
            deletions = 0
            status = "modified"
            continue

        if line.startswith("new file"):
            status = "added"
            continue
        if line.startswith("deleted file"):
            status = "removed"
            continue
        if line.startswith("rename from"):
            status = "renamed"
            continue
        if BINARY_FILE_RE.match(line):
            status = "modified"
            current_patch_lines.append(line)
            continue

        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("index "):
            continue

        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            hunk = _parse_hunk_header(line, hunk_match)
            current_hunks.append(hunk)
            current_patch_lines.append(line)
            continue

        if current_filename is not None:
            current_patch_lines.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

    if current_filename is not None:
        files.append(
            _build_file_change(
                current_filename,
                status,
                current_patch_lines,
                current_hunks,
                additions,
                deletions,
            )
        )

    logger.info("Parsed %d files from unified diff", len(files))
    return files


def parse_hunk_header(header: str) -> DiffHunk | None:
    """Parse a single hunk header line into a DiffHunk model.

    Args:
        header: A line like ``@@ -10,5 +12,7 @@ def foo():``

    Returns:
        Parsed DiffHunk or None if the header doesn't match.
    """
    match = HUNK_HEADER_RE.match(header)
    if not match:
        return None
    return _parse_hunk_header(header, match)


def extract_changed_lines(patch: str) -> list[tuple[int, str]]:
    """Extract added/modified lines with their new-file line numbers.

    Args:
        patch: A unified diff patch for a single file.

    Returns:
        List of (line_number, line_content) tuples for added lines.
    """
    if not patch:
        return []

    changed: list[tuple[int, str]] = []
    current_line = 0

    for line in patch.split("\n"):
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            current_line = int(hunk_match.group(3))
            continue

        if line.startswith("+") and not line.startswith("+++"):
            changed.append((current_line, line[1:]))
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        else:
            current_line += 1

    return changed


def _parse_hunk_header(header: str, match: re.Match[str]) -> DiffHunk:
    """Build a DiffHunk from a regex match on a hunk header."""
    return DiffHunk(
        old_start=int(match.group(1)),
        old_count=int(match.group(2) or "1"),
        new_start=int(match.group(3)),
        new_count=int(match.group(4) or "1"),
        content="",
        header=match.group(5).strip(),
    )


def _build_file_change(
    filename: str,
    status: str,
    patch_lines: list[str],
    hunks: list[DiffHunk],
    additions: int,
    deletions: int,
) -> FileChange:
    """Construct a FileChange model from accumulated parse state."""
    return FileChange(
        filename=filename,
        status=status,
        patch="\n".join(patch_lines),
        additions=additions,
        deletions=deletions,
        hunks=hunks,
    )
