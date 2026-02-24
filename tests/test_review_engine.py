"""Tests for the review engine module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai_code_reviewer.models import (
    FileChange,
    IssueCategory,
    ReviewIssue,
    Severity,
)
from ai_code_reviewer.review_engine import ReviewEngine


class FakeGeminiClient:
    """Test double that returns a configurable analysis response."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.model_name = "test-model"
        self.calls: list[tuple[str, str]] = []
        self._response = response or {
            "summary": "Test review summary.",
            "overall_score": 85,
            "issues": [
                {
                    "severity": "medium",
                    "category": "style",
                    "file": "test.py",
                    "line": 10,
                    "description": "Variable name too short.",
                    "recommendation": "Use a descriptive name.",
                    "confidence": 0.8,
                }
            ],
        }

    def analyze_code(self, prompt: str, code: str) -> dict[str, Any]:
        self.calls.append((prompt, code))
        return self._response


@pytest.fixture
def engine() -> ReviewEngine:
    return ReviewEngine(gemini_client=FakeGeminiClient(), max_file_size=50_000)


@pytest.fixture
def sample_files() -> list[FileChange]:
    return [
        FileChange(
            filename="app.py",
            status="modified",
            patch="+ print('hello')",
            additions=1,
            deletions=0,
        ),
        FileChange(
            filename="utils.py",
            status="added",
            patch="+ def helper(): pass",
            additions=1,
            deletions=0,
        ),
    ]


class TestCalculateScore:
    def test_no_issues_returns_100(self) -> None:
        assert ReviewEngine._calculate_score([]) == 100

    def test_single_low_issue(self) -> None:
        issues = [
            ReviewIssue(
                severity=Severity.LOW,
                category=IssueCategory.STYLE,
                file="a.py",
                description="x",
                recommendation="y",
                confidence=0.5,
            )
        ]
        assert ReviewEngine._calculate_score(issues) == 98

    def test_critical_issue_heavy_penalty(self) -> None:
        issues = [
            ReviewIssue(
                severity=Severity.CRITICAL,
                category=IssueCategory.SECURITY,
                file="a.py",
                description="x",
                recommendation="y",
                confidence=0.9,
            )
        ]
        assert ReviewEngine._calculate_score(issues) == 75

    def test_multiple_issues_compound(self) -> None:
        issues = [
            ReviewIssue(
                severity=Severity.HIGH,
                category=IssueCategory.BUG,
                file="a.py",
                description="x",
                recommendation="y",
                confidence=0.8,
            ),
            ReviewIssue(
                severity=Severity.MEDIUM,
                category=IssueCategory.PERFORMANCE,
                file="b.py",
                description="x",
                recommendation="y",
                confidence=0.7,
            ),
        ]
        # 100 - 15 - 5 = 80
        assert ReviewEngine._calculate_score(issues) == 80

    def test_score_floors_at_zero(self) -> None:
        issues = [
            ReviewIssue(
                severity=Severity.CRITICAL,
                category=IssueCategory.SECURITY,
                file="a.py",
                description="x",
                recommendation="y",
                confidence=0.9,
            )
            for _ in range(10)
        ]
        assert ReviewEngine._calculate_score(issues) == 0


class TestChunkFiles:
    def test_small_files_single_chunk(self, engine: ReviewEngine) -> None:
        files = [
            FileChange(filename="a.py", patch="x" * 100),
            FileChange(filename="b.py", patch="x" * 100),
        ]
        chunks = engine._chunk_files(files, max_chunk_size=500)
        assert len(chunks) == 1
        assert len(chunks[0]) == 2

    def test_large_files_split_across_chunks(self, engine: ReviewEngine) -> None:
        files = [
            FileChange(filename="a.py", patch="x" * 500),
            FileChange(filename="b.py", patch="x" * 500),
            FileChange(filename="c.py", patch="x" * 500),
        ]
        chunks = engine._chunk_files(files, max_chunk_size=600)
        assert len(chunks) == 3

    def test_empty_files_list(self, engine: ReviewEngine) -> None:
        chunks = engine._chunk_files([], max_chunk_size=1000)
        assert chunks == []


class TestBuildReviewPrompt:
    def test_prompt_contains_filenames(self, engine: ReviewEngine, sample_files: list[FileChange]) -> None:
        prompt = engine._build_review_prompt(sample_files, context="test")
        assert "app.py" in prompt
        assert "utils.py" in prompt

    def test_prompt_contains_security_checklist(self, engine: ReviewEngine, sample_files: list[FileChange]) -> None:
        prompt = engine._build_review_prompt(sample_files)
        assert "SQL injection" in prompt
        assert "Hardcoded secrets" in prompt
        assert "deserialization" in prompt


class TestAggregateResults:
    def test_merges_issues_from_multiple_results(self, engine: ReviewEngine) -> None:
        raw_results = [
            {
                "summary": "Part 1",
                "overall_score": 90,
                "issues": [
                    {
                        "severity": "low",
                        "category": "style",
                        "file": "a.py",
                        "description": "issue 1",
                        "recommendation": "fix 1",
                        "confidence": 0.5,
                    }
                ],
            },
            {
                "summary": "Part 2",
                "overall_score": 70,
                "issues": [
                    {
                        "severity": "high",
                        "category": "bug",
                        "file": "b.py",
                        "description": "issue 2",
                        "recommendation": "fix 2",
                        "confidence": 0.8,
                    }
                ],
            },
        ]
        result = engine._aggregate_results(raw_results, files_reviewed=2)
        assert len(result.issues) == 2
        assert "Part 1" in result.summary
        assert "Part 2" in result.summary

    def test_recalculates_score(self, engine: ReviewEngine) -> None:
        raw_results = [
            {
                "summary": "Clean",
                "overall_score": 100,
                "issues": [],
            }
        ]
        result = engine._aggregate_results(raw_results, files_reviewed=1)
        assert result.overall_score == 100


class TestFilterReviewable:
    def test_filters_binary_files(self, engine: ReviewEngine) -> None:
        files = [
            FileChange(filename="app.py", patch="code"),
            FileChange(filename="image.png", patch="Binary files differ"),
        ]
        result = engine._filter_reviewable(files)
        assert len(result) == 1
        assert result[0].filename == "app.py"

    def test_filters_non_source_extensions(self, engine: ReviewEngine) -> None:
        files = [
            FileChange(filename="app.py", patch="code"),
            FileChange(filename="readme.md", patch="text"),
            FileChange(filename="data.csv", patch="1,2,3"),
        ]
        result = engine._filter_reviewable(files)
        assert len(result) == 1

    def test_filters_empty_patches(self, engine: ReviewEngine) -> None:
        files = [
            FileChange(filename="empty.py", patch=""),
        ]
        result = engine._filter_reviewable(files)
        assert len(result) == 0


class TestReviewSingleFile:
    def test_reviews_file_with_fake_gemini(self, tmp_path: Path) -> None:
        test_file = tmp_path / "sample.py"
        test_file.write_text("def foo():\n    return 42\n")

        fake_gemini = FakeGeminiClient()
        engine = ReviewEngine(gemini_client=fake_gemini)
        result = engine.review_single_file(str(test_file))

        assert result.overall_score > 0
        assert result.metadata.files_reviewed == 1
        assert result.metadata.review_type == "single_file"
        assert len(fake_gemini.calls) == 1

    def test_nonexistent_file_raises(self) -> None:
        fake_gemini = FakeGeminiClient()
        engine = ReviewEngine(gemini_client=fake_gemini)
        with pytest.raises(FileNotFoundError):
            engine.review_single_file("/nonexistent/file.py")
