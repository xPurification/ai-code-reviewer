"""Report rendering for code review results.

Provides Rich-formatted terminal output and JSON export for review
results.  Terminal reports include color-coded severity indicators,
grouped issue tables, and an executive summary panel.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ai_code_reviewer.models import ReviewIssue, ReviewResult, Severity

console = Console()

SEVERITY_COLORS: dict[Severity, str] = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
}

SEVERITY_ICONS: dict[Severity, str] = {
    Severity.CRITICAL: "[bold red]CRIT[/]",
    Severity.HIGH: "[red]HIGH[/]",
    Severity.MEDIUM: "[yellow]MED [/]",
    Severity.LOW: "[cyan]LOW [/]",
}


def render_terminal_report(result: ReviewResult) -> None:
    """Render a full review report to the terminal using Rich.

    Displays an executive summary panel, score indicator, categorized
    issue table, and actionable recommendations.

    Args:
        result: The review result to render.
    """
    console.print()
    _render_header()
    _render_summary_panel(result)
    _render_score(result.overall_score)

    if result.issues:
        _render_issues_table(result.issues)
        _render_category_breakdown(result)
        _render_recommendations(result)
    else:
        console.print(
            Panel(
                "[green]No issues found. Code looks clean![/]",
                title="Results",
                border_style="green",
            )
        )

    _render_metadata(result)
    console.print()


def export_json_report(result: ReviewResult, output_path: str | None = None) -> str:
    """Export the review result as a JSON string.

    Args:
        result: The review result to export.
        output_path: Optional file path to write the JSON.
                     If None, returns the JSON string without writing.

    Returns:
        The JSON string representation of the result.
    """
    data = result.model_dump(mode="json")
    json_str = json.dumps(data, indent=2, default=str)

    if output_path:
        path = Path(output_path)
        path.write_text(json_str, encoding="utf-8")
        console.print(f"[green]Report written to {path}[/]")

    return json_str


def format_issue(issue: ReviewIssue) -> str:
    """Format a single issue as a human-readable string.

    Args:
        issue: The review issue to format.

    Returns:
        Formatted issue string.
    """
    location = f"{issue.file}"
    if issue.line:
        location += f":{issue.line}"
    return (
        f"[{issue.severity.upper()}] ({issue.category}) {location}\n"
        f"  {issue.description}\n"
        f"  Fix: {issue.recommendation}"
    )


def _render_header() -> None:
    console.print(
        Panel(
            "[bold]AI Code Review Assistant[/]\n"
            "Automated analysis powered by Google Gemini",
            border_style="blue",
        )
    )


def _render_summary_panel(result: ReviewResult) -> None:
    summary_text = result.summary or "Review complete."
    issue_count = len(result.issues)
    critical = len(result.critical_issues)
    high = len(result.high_issues)

    stats = f"[bold]{issue_count}[/] issue(s) found"
    if critical:
        stats += f" | [bold red]{critical} critical[/]"
    if high:
        stats += f" | [red]{high} high[/]"

    console.print(
        Panel(
            f"{summary_text}\n\n{stats}",
            title="Executive Summary",
            border_style="blue",
        )
    )


def _render_score(score: int) -> None:
    if score > 80:
        color = "green"
        label = "Excellent"
    elif score > 60:
        color = "yellow"
        label = "Acceptable"
    elif score > 40:
        color = "red"
        label = "Needs Improvement"
    else:
        color = "bold red"
        label = "Critical Issues"

    bar_filled = score // 2
    bar_empty = 50 - bar_filled
    bar = f"[{color}]{'█' * bar_filled}[/]{'░' * bar_empty}"

    console.print(
        Panel(
            f"Score: [{color}]{score}/100[/] — {label}\n{bar}",
            title="Quality Score",
            border_style=color,
        )
    )


def _render_issues_table(issues: list[ReviewIssue]) -> None:
    table = Table(
        title="Issues Found",
        show_header=True,
        header_style="bold",
        show_lines=True,
        expand=True,
    )
    table.add_column("Sev", width=5, justify="center")
    table.add_column("Category", width=16)
    table.add_column("Location", width=28)
    table.add_column("Description", ratio=2)
    table.add_column("Recommendation", ratio=2)
    table.add_column("Conf", width=5, justify="center")

    severity_order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
    sorted_issues = sorted(issues, key=lambda i: severity_order.index(i.severity))

    for issue in sorted_issues:
        sev_display = SEVERITY_ICONS.get(issue.severity, str(issue.severity))
        color = SEVERITY_COLORS.get(issue.severity, "white")
        location = issue.file
        if issue.line:
            location += f":{issue.line}"

        table.add_row(
            sev_display,
            issue.category.value,
            Text(location, style="dim"),
            Text(issue.description, style=color),
            issue.recommendation,
            f"{issue.confidence:.0%}",
        )

    console.print(table)


def _render_category_breakdown(result: ReviewResult) -> None:
    by_category = result.issues_by_category
    if not by_category:
        return

    table = Table(title="Category Breakdown", show_header=True, header_style="bold")
    table.add_column("Category", width=20)
    table.add_column("Count", width=8, justify="center")
    table.add_column("Worst Severity", width=16)

    severity_rank = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}

    for category, issues in sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True):
        worst = max(issues, key=lambda i: severity_rank[i.severity])
        color = SEVERITY_COLORS.get(worst.severity, "white")
        table.add_row(
            category.value,
            str(len(issues)),
            Text(worst.severity.value, style=color),
        )

    console.print(table)


def _render_recommendations(result: ReviewResult) -> None:
    critical_and_high = [
        i for i in result.issues if i.severity in (Severity.CRITICAL, Severity.HIGH)
    ]
    if not critical_and_high:
        return

    lines = ["[bold]Priority fixes:[/]\n"]
    for i, issue in enumerate(critical_and_high[:5], 1):
        location = issue.file
        if issue.line:
            location += f":{issue.line}"
        color = SEVERITY_COLORS.get(issue.severity, "white")
        lines.append(
            f"  [{color}]{i}. [{issue.severity.upper()}][/] {location}\n"
            f"     {issue.recommendation}\n"
        )

    console.print(
        Panel(
            "\n".join(lines),
            title="Recommended Actions",
            border_style="red",
        )
    )


def _render_metadata(result: ReviewResult) -> None:
    meta = result.metadata
    parts = [
        f"Files reviewed: {meta.files_reviewed}",
        f"Duration: {meta.duration_seconds:.1f}s",
        f"Model: {meta.model_used}",
        f"Type: {meta.review_type}",
    ]
    console.print(
        Panel(
            " | ".join(parts),
            title="Review Metadata",
            border_style="dim",
        )
    )
