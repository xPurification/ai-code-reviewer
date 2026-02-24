"""Command-line interface for the AI Code Review Assistant.

Provides Click commands for reviewing GitHub pull requests, local
directories, and individual files.  All commands support terminal
and JSON output formats.
"""

from __future__ import annotations

import sys
from typing import NoReturn

import click
from rich.console import Console
from rich.table import Table

from ai_code_reviewer.config import ConfigurationError, get_settings
from ai_code_reviewer.gemini_client import GeminiClient, GeminiClientError
from ai_code_reviewer.github_client import GitHubClient, GitHubClientError
from ai_code_reviewer.logging_config import setup_logging
from ai_code_reviewer.models import ReviewResult
from ai_code_reviewer.report import export_json_report, render_terminal_report
from ai_code_reviewer.review_engine import ReviewEngine

console = Console(stderr=True)


@click.group()
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable debug logging."
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """AI Code Review Assistant - Automated code reviews powered by Google Gemini."""
    ctx.ensure_object(dict)
    settings = get_settings()
    level = "DEBUG" if verbose else settings.log_level
    setup_logging(level)
    ctx.obj["settings"] = settings
    ctx.obj["verbose"] = verbose


@cli.command("review-pr")
@click.option(
    "--repo",
    required=True,
    help="GitHub repository in owner/repo format.",
)
@click.option(
    "--pr-number",
    required=True,
    type=int,
    help="Pull request number to review.",
)
@click.option(
    "--output",
    type=click.Choice(["terminal", "json"]),
    default="terminal",
    help="Output format.",
)
@click.pass_context
def review_pr(ctx: click.Context, repo: str, pr_number: int, output: str) -> None:
    """Review a GitHub pull request for code quality and security issues."""
    settings = ctx.obj["settings"]

    if "/" not in repo:
        _error_exit("Repository must be in 'owner/repo' format.")

    owner, repo_name = repo.split("/", 1)

    try:
        token = settings.require_github_token()
        api_key = settings.require_gemini_api_key()
    except ConfigurationError as exc:
        _error_exit(str(exc))

    try:
        github_client = GitHubClient(
            token=token,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
        )
        gemini_client = GeminiClient(
            api_key=api_key,
            model_name=settings.gemini_model,
            max_retries=settings.max_retries,
            timeout=settings.request_timeout,
        )
        engine = ReviewEngine(
            gemini_client=gemini_client,
            max_file_size=settings.max_file_size,
        )

        result = engine.review_pr(github_client, owner, repo_name, pr_number)
        _output_result(result, output)

    except GitHubClientError as exc:
        _error_exit(f"GitHub API error: {exc}")
    except GeminiClientError as exc:
        _error_exit(f"Gemini API error: {exc}")
    except Exception as exc:
        _error_exit(f"Unexpected error: {exc}")


@cli.command("review-local")
@click.option(
    "--path",
    default=".",
    type=click.Path(exists=True),
    help="Path to the directory to review.",
)
@click.option(
    "--output",
    type=click.Choice(["terminal", "json"]),
    default="terminal",
    help="Output format.",
)
@click.pass_context
def review_local(ctx: click.Context, path: str, output: str) -> None:
    """Review all source files in a local directory."""
    settings = ctx.obj["settings"]

    try:
        api_key = settings.require_gemini_api_key()
    except ConfigurationError as exc:
        _error_exit(str(exc))

    try:
        gemini_client = GeminiClient(
            api_key=api_key,
            model_name=settings.gemini_model,
            max_retries=settings.max_retries,
            timeout=settings.request_timeout,
        )
        engine = ReviewEngine(
            gemini_client=gemini_client,
            max_file_size=settings.max_file_size,
        )

        result = engine.review_local_directory(path)
        _output_result(result, output)

    except FileNotFoundError as exc:
        _error_exit(str(exc))
    except GeminiClientError as exc:
        _error_exit(f"Gemini API error: {exc}")
    except Exception as exc:
        _error_exit(f"Unexpected error: {exc}")


@cli.command("review-file")
@click.option(
    "--path",
    required=True,
    type=click.Path(exists=True),
    help="Path to the file to review.",
)
@click.pass_context
def review_file(ctx: click.Context, path: str) -> None:
    """Review a single source file."""
    settings = ctx.obj["settings"]

    try:
        api_key = settings.require_gemini_api_key()
    except ConfigurationError as exc:
        _error_exit(str(exc))

    try:
        gemini_client = GeminiClient(
            api_key=api_key,
            model_name=settings.gemini_model,
            max_retries=settings.max_retries,
            timeout=settings.request_timeout,
        )
        engine = ReviewEngine(
            gemini_client=gemini_client,
            max_file_size=settings.max_file_size,
        )

        result = engine.review_single_file(path)
        render_terminal_report(result)

    except FileNotFoundError as exc:
        _error_exit(str(exc))
    except GeminiClientError as exc:
        _error_exit(f"Gemini API error: {exc}")
    except Exception as exc:
        _error_exit(f"Unexpected error: {exc}")


@cli.group("config")
def config_group() -> None:
    """Manage configuration settings."""


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration (secrets are masked)."""
    settings = ctx.obj["settings"]
    display = settings.masked_display()

    table = Table(title="Configuration", show_header=True, header_style="bold")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    for key, value in display.items():
        style = "dim" if value == "(not set)" else ""
        table.add_row(key, value, style=style)

    output_console = Console()
    output_console.print(table)


def _output_result(result: ReviewResult, output_format: str) -> None:
    """Route the result to the appropriate output handler."""
    if output_format == "json":
        json_str = export_json_report(result)
        click.echo(json_str)
    else:
        render_terminal_report(result)


def _error_exit(message: str) -> NoReturn:
    """Print an error message and exit with a non-zero status code."""
    console.print(f"[bold red]Error:[/] {message}")
    sys.exit(1)
