"""Review engine that orchestrates the code analysis pipeline.

Coordinates between the GitHub client, Gemini client, and diff parser
to produce structured review results.  Supports PR reviews, local
directory scans, and single-file reviews.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ai_code_reviewer.gemini_client import GeminiClient
from ai_code_reviewer.github_client import GitHubClient
from ai_code_reviewer.logging_config import get_logger
from ai_code_reviewer.models import (
    FileChange,
    IssueCategory,
    ReviewIssue,
    ReviewMetadata,
    ReviewResult,
    Severity,
)

logger = get_logger(__name__)

REVIEWABLE_EXTENSIONS = {
    "py", "js", "ts", "tsx", "jsx", "java", "go", "rs", "rb",
    "c", "cpp", "h", "hpp", "cs", "php", "swift", "kt", "scala",
    "sh", "bash", "yaml", "yml", "toml", "json", "sql", "html",
    "css", "scss", "vue", "svelte",
}

SEVERITY_PENALTIES: dict[Severity, int] = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 15,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
}


class ReviewEngine:
    """Orchestrates code review analysis using AI.

    Args:
        gemini_client: Configured Gemini API client for code analysis.
        max_file_size: Maximum file content size in characters.
    """

    def __init__(
        self,
        gemini_client: GeminiClient,
        max_file_size: int = 50_000,
    ) -> None:
        self._gemini = gemini_client
        self._max_file_size = max_file_size

    def review_pr(
        self,
        github_client: GitHubClient,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> ReviewResult:
        """Run a full review of a GitHub pull request.

        Fetches the PR's changed files, chunks them if necessary,
        sends each chunk to Gemini for analysis, and aggregates results.

        Args:
            github_client: Authenticated GitHub API client.
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            Aggregated review result with scored issues.
        """
        start = time.monotonic()
        logger.info("Starting review of PR #%d in %s/%s", pr_number, owner, repo)

        files = github_client.get_pr_files(owner, repo, pr_number)
        reviewable = self._filter_reviewable(files)
        logger.info(
            "Found %d reviewable files out of %d total", len(reviewable), len(files)
        )

        if not reviewable:
            return ReviewResult(
                summary="No reviewable files found in this pull request.",
                overall_score=100,
                metadata=ReviewMetadata(
                    duration_seconds=time.monotonic() - start,
                    files_reviewed=0,
                    model_used=self._gemini.model_name,
                    review_type="pull_request",
                ),
            )

        chunks = self._chunk_files(reviewable)
        partial_results = []
        for i, chunk in enumerate(chunks, 1):
            logger.info("Analyzing chunk %d/%d", i, len(chunks))
            prompt = self._build_review_prompt(chunk, context="pull request diff")
            code = self._format_files_for_review(chunk)
            raw_result = self._gemini.analyze_code(prompt, code)
            partial_results.append(raw_result)

        result = self._aggregate_results(partial_results, len(reviewable))
        result.metadata = ReviewMetadata(
            duration_seconds=time.monotonic() - start,
            files_reviewed=len(reviewable),
            model_used=self._gemini.model_name,
            review_type="pull_request",
        )
        return result

    def review_local_directory(self, path: str | Path) -> ReviewResult:
        """Review all supported source files in a local directory.

        Recursively scans the directory for source files, reads their
        contents, and performs AI analysis.

        Args:
            path: Path to the directory to review.

        Returns:
            Aggregated review result.
        """
        start = time.monotonic()
        dir_path = Path(path).resolve()
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        logger.info("Scanning directory: %s", dir_path)
        files = self._collect_local_files(dir_path)
        if not files:
            return ReviewResult(
                summary="No reviewable source files found in the directory.",
                overall_score=100,
                metadata=ReviewMetadata(
                    duration_seconds=time.monotonic() - start,
                    files_reviewed=0,
                    model_used=self._gemini.model_name,
                    review_type="local_directory",
                ),
            )

        logger.info("Found %d reviewable files", len(files))
        chunks = self._chunk_files(files)
        partial_results = []
        for i, chunk in enumerate(chunks, 1):
            logger.info("Analyzing chunk %d/%d", i, len(chunks))
            prompt = self._build_review_prompt(chunk, context="local source files")
            code = self._format_files_for_review(chunk)
            raw_result = self._gemini.analyze_code(prompt, code)
            partial_results.append(raw_result)

        result = self._aggregate_results(partial_results, len(files))
        result.metadata = ReviewMetadata(
            duration_seconds=time.monotonic() - start,
            files_reviewed=len(files),
            model_used=self._gemini.model_name,
            review_type="local_directory",
        )
        return result

    def review_single_file(self, path: str | Path) -> ReviewResult:
        """Review a single source file.

        Args:
            path: Path to the file to review.

        Returns:
            Review result for the single file.
        """
        start = time.monotonic()
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = file_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > self._max_file_size:
            content = content[: self._max_file_size]
            logger.warning(
                "File %s truncated to %d chars", file_path.name, self._max_file_size
            )

        file_change = FileChange(
            filename=file_path.name,
            status="review",
            patch=content,
        )

        prompt = self._build_review_prompt([file_change], context="single file review")
        code = f"=== {file_path.name} ===\n{content}"
        raw_result = self._gemini.analyze_code(prompt, code)

        result = self._parse_raw_result(raw_result)
        result.metadata = ReviewMetadata(
            duration_seconds=time.monotonic() - start,
            files_reviewed=1,
            model_used=self._gemini.model_name,
            review_type="single_file",
        )
        return result

    def _filter_reviewable(self, files: list[FileChange]) -> list[FileChange]:
        """Filter files to only those with reviewable source extensions."""
        return [
            f
            for f in files
            if f.extension in REVIEWABLE_EXTENSIONS
            and not f.is_binary
            and f.patch
        ]

    def _collect_local_files(self, directory: Path) -> list[FileChange]:
        """Recursively collect source files from a local directory."""
        files: list[FileChange] = []
        skip_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
            ".egg-info",
        }

        for file_path in sorted(directory.rglob("*")):
            if any(part in skip_dirs for part in file_path.parts):
                continue
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lstrip(".")
            if ext not in REVIEWABLE_EXTENSIONS:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError) as exc:
                logger.warning("Skipping %s: %s", file_path, exc)
                continue

            if len(content) > self._max_file_size:
                content = content[: self._max_file_size]

            relative = file_path.relative_to(directory)
            files.append(
                FileChange(
                    filename=str(relative),
                    status="review",
                    patch=content,
                )
            )

        return files

    def _chunk_files(
        self, files: list[FileChange], max_chunk_size: int = 40_000
    ) -> list[list[FileChange]]:
        """Group files into chunks that fit within the size limit.

        Splits at file boundaries first.  Files larger than the limit
        are included alone in their own chunk (and may be internally
        truncated by the Gemini client).
        """
        chunks: list[list[FileChange]] = []
        current_chunk: list[FileChange] = []
        current_size = 0

        for f in files:
            file_size = len(f.patch) + len(f.filename) + 20
            if current_size + file_size > max_chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            current_chunk.append(f)
            current_size += file_size

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _build_review_prompt(
        self, files: list[FileChange], context: str = ""
    ) -> str:
        """Construct the review prompt with file listing and security checklist."""
        file_list = "\n".join(f"  - {f.filename} ({f.status})" for f in files)
        return (
            f"Review the following {context} containing {len(files)} file(s):\n"
            f"{file_list}\n\n"
            "Pay special attention to these security concerns:\n"
            "- SQL injection or command injection vulnerabilities\n"
            "- Unsafe deserialization of user input\n"
            "- Hardcoded secrets, API keys, or credentials\n"
            "- Insecure dependency patterns or known vulnerable APIs\n"
            "- Authentication or authorization bypasses\n"
            "- Path traversal or file inclusion vulnerabilities\n"
            "- Cross-site scripting (XSS) in web code\n\n"
            "Provide your analysis as structured JSON."
        )

    @staticmethod
    def _format_files_for_review(files: list[FileChange]) -> str:
        """Format file contents into a single string for the AI model."""
        sections = []
        for f in files:
            sections.append(f"=== {f.filename} ({f.status}) ===\n{f.patch}")
        return "\n\n".join(sections)

    def _aggregate_results(
        self, raw_results: list[dict[str, Any]], files_reviewed: int
    ) -> ReviewResult:
        """Merge multiple partial review results into a single ReviewResult."""
        all_issues: list[ReviewIssue] = []
        summaries: list[str] = []

        for raw in raw_results:
            parsed = self._parse_raw_result(raw)
            all_issues.extend(parsed.issues)
            if parsed.summary:
                summaries.append(parsed.summary)

        score = self._calculate_score(all_issues)
        combined_summary = " ".join(summaries) if summaries else "Review complete."

        return ReviewResult(
            summary=combined_summary,
            overall_score=score,
            issues=all_issues,
        )

    @staticmethod
    def _parse_raw_result(raw: dict[str, Any]) -> ReviewResult:
        """Parse a raw JSON dict from Gemini into a ReviewResult."""
        issues: list[ReviewIssue] = []
        for item in raw.get("issues", []):
            try:
                issues.append(
                    ReviewIssue(
                        severity=Severity(item.get("severity", "low")),
                        category=IssueCategory(item.get("category", "style")),
                        file=item.get("file", "unknown"),
                        line=item.get("line"),
                        description=item.get("description", ""),
                        recommendation=item.get("recommendation", ""),
                        confidence=item.get("confidence", 0.5),
                    )
                )
            except (ValueError, KeyError) as exc:
                logger.warning("Skipping malformed issue: %s (%s)", item, exc)

        score = raw.get("overall_score", 100)
        score = max(0, min(100, int(score)))

        return ReviewResult(
            summary=raw.get("summary", ""),
            overall_score=score,
            issues=issues,
        )

    @staticmethod
    def _calculate_score(issues: list[ReviewIssue]) -> int:
        """Calculate an overall quality score from the issue list.

        Starts at 100 and subtracts weighted penalties per issue severity.
        The score is floored at 0.
        """
        score = 100
        for issue in issues:
            penalty = SEVERITY_PENALTIES.get(issue.severity, 2)
            score -= penalty
        return max(0, score)
