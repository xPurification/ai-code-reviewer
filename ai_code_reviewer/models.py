"""Domain models for the AI Code Review Assistant.

All data structures are defined here to avoid circular imports and provide
a single source of truth for the type system.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    """Issue severity levels ordered by impact."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueCategory(StrEnum):
    """Classification categories for code review issues."""

    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    MAINTAINABILITY = "maintainability"


class ReviewIssue(BaseModel):
    """A single issue identified during code review."""

    severity: Severity
    category: IssueCategory
    file: str
    line: int | None = None
    description: str
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: Any) -> float:
        """Clamp confidence to [0, 1] range to handle model imprecision."""
        if isinstance(v, (int, float)):
            return max(0.0, min(1.0, float(v)))
        return v


class ReviewMetadata(BaseModel):
    """Metadata about a review run."""

    timestamp: datetime = Field(default_factory=datetime.now)
    duration_seconds: float = 0.0
    files_reviewed: int = 0
    model_used: str = ""
    review_type: str = ""


class ReviewResult(BaseModel):
    """Complete result of a code review analysis."""

    summary: str
    overall_score: int = Field(ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list)
    metadata: ReviewMetadata = Field(default_factory=ReviewMetadata)

    @property
    def critical_issues(self) -> list[ReviewIssue]:
        return [i for i in self.issues if i.severity == Severity.CRITICAL]

    @property
    def high_issues(self) -> list[ReviewIssue]:
        return [i for i in self.issues if i.severity == Severity.HIGH]

    @property
    def issues_by_category(self) -> dict[IssueCategory, list[ReviewIssue]]:
        grouped: dict[IssueCategory, list[ReviewIssue]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.category, []).append(issue)
        return grouped

    @property
    def issues_by_severity(self) -> dict[Severity, list[ReviewIssue]]:
        grouped: dict[Severity, list[ReviewIssue]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.severity, []).append(issue)
        return grouped


class DiffHunk(BaseModel):
    """A single hunk from a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    header: str = ""


class FileChange(BaseModel):
    """A file changed in a pull request or diff."""

    filename: str
    status: str = "modified"
    patch: str = ""
    additions: int = 0
    deletions: int = 0
    hunks: list[DiffHunk] = Field(default_factory=list)

    @property
    def extension(self) -> str:
        parts = self.filename.rsplit(".", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def is_binary(self) -> bool:
        return "Binary files" in self.patch or self.patch == ""


class PRMetadata(BaseModel):
    """Pull request metadata from GitHub."""

    number: int
    title: str
    author: str
    base_branch: str
    head_branch: str
    description: str = ""
    url: str = ""
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
