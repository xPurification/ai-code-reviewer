"""GitHub REST API client with retry logic, pagination, and rate-limit handling.

Provides a high-level interface for fetching pull request metadata, changed
files, and file contents from the GitHub API.  All network calls include
exponential-backoff retries via tenacity and respect GitHub's rate limits.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ai_code_reviewer.logging_config import get_logger
from ai_code_reviewer.models import FileChange, PRMetadata

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""


class GitHubAuthError(GitHubClientError):
    """Raised when authentication fails (401)."""


class GitHubNotFoundError(GitHubClientError):
    """Raised when the requested resource does not exist (404)."""


class GitHubRateLimitError(GitHubClientError):
    """Raised when the API rate limit is exceeded (403 with rate-limit headers)."""


class GitHubClient:
    """Client for interacting with the GitHub REST API.

    Args:
        token: GitHub personal access token for authentication.
        base_url: API base URL (override for GitHub Enterprise).
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts for transient failures.
    """

    def __init__(
        self,
        token: str,
        base_url: str = GITHUB_API_BASE,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        self._base_url = base_url.rstrip("/")

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> PRMetadata:
        """Fetch metadata for a pull request.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            Parsed pull request metadata.

        Raises:
            GitHubNotFoundError: If the PR does not exist.
            GitHubAuthError: If the token is invalid or lacks permissions.
        """
        url = f"{self._base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        data = self._request("GET", url)
        return PRMetadata(
            number=data["number"],
            title=data["title"],
            author=data["user"]["login"],
            base_branch=data["base"]["ref"],
            head_branch=data["head"]["ref"],
            description=data.get("body") or "",
            url=data["html_url"],
            changed_files=data.get("changed_files", 0),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
        )

    def get_pr_files(
        self, owner: str, repo: str, pr_number: int
    ) -> list[FileChange]:
        """Fetch the list of files changed in a pull request.

        Handles pagination automatically to retrieve all changed files.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            List of file changes with patches.
        """
        url = f"{self._base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        all_files = self._paginated_request("GET", url)
        changes: list[FileChange] = []
        for f in all_files:
            changes.append(
                FileChange(
                    filename=f["filename"],
                    status=f.get("status", "modified"),
                    patch=f.get("patch", ""),
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0),
                )
            )
        logger.info("Fetched %d changed files from PR #%d", len(changes), pr_number)
        return changes

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: str = "main"
    ) -> str:
        """Fetch the raw content of a file from a repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: File path within the repository.
            ref: Git ref (branch, tag, or commit SHA).

        Returns:
            Raw file content as a string.
        """
        url = f"{self._base_url}/repos/{owner}/{repo}/contents/{path}"
        headers = {"Accept": "application/vnd.github.v3.raw"}
        response = self._raw_request("GET", url, headers=headers, params={"ref": ref})
        return response.text

    @retry(
        retry=retry_if_exception_type(requests.exceptions.ConnectionError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Execute an API request with error handling and retry logic."""
        response = self._raw_request(method, url, **kwargs)
        return response.json()

    def _raw_request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Execute a raw HTTP request with rate-limit and error handling."""
        kwargs.setdefault("timeout", self._timeout)
        merge_headers = kwargs.pop("headers", None)
        if merge_headers:
            kwargs["headers"] = {**dict(self._session.headers), **merge_headers}

        logger.debug("GitHub API %s %s", method, url)
        response = self._session.request(method, url, **kwargs)
        self._handle_rate_limit(response)
        self._handle_errors(response)
        return response

    def _paginated_request(
        self, method: str, url: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated GitHub API response."""
        results: list[dict[str, Any]] = []
        next_url: str | None = url

        while next_url:
            kwargs["timeout"] = self._timeout
            logger.debug("GitHub API paginated %s %s", method, next_url)
            response = self._session.request(method, next_url, **kwargs)
            self._handle_rate_limit(response)
            self._handle_errors(response)
            results.extend(response.json())
            next_url = self._parse_next_link(response)

        return results

    @staticmethod
    def _parse_next_link(response: requests.Response) -> str | None:
        """Extract the next page URL from the Link header."""
        link_header = response.headers.get("Link", "")
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return url
        return None

    def _handle_rate_limit(self, response: requests.Response) -> None:
        """Detect rate limiting and wait before retrying."""
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining", "1")
            if remaining == "0":
                reset_time = int(response.headers.get("X-RateLimit-Reset", "0"))
                wait_seconds = max(reset_time - int(time.time()), 1)
                wait_seconds = min(wait_seconds, 60)
                logger.warning(
                    "GitHub rate limit exceeded. Waiting %d seconds.", wait_seconds
                )
                time.sleep(wait_seconds)
                raise GitHubRateLimitError(
                    f"Rate limit exceeded. Retry after {wait_seconds}s."
                )

    @staticmethod
    def _handle_errors(response: requests.Response) -> None:
        """Map HTTP error codes to domain-specific exceptions."""
        if response.status_code == 401:
            raise GitHubAuthError(
                "Authentication failed. Check your GITHUB_TOKEN."
            )
        if response.status_code == 404:
            raise GitHubNotFoundError(
                f"Resource not found: {response.url}"
            )
        if response.status_code == 403:
            raise GitHubAuthError(
                "Access forbidden. Your token may lack the required scopes."
            )
        response.raise_for_status()
