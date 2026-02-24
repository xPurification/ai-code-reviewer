"""Tests for the GitHub client module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from ai_code_reviewer.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubNotFoundError,
    GitHubRateLimitError,
)


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(token="test-token-123", timeout=5, max_retries=1)


def _mock_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    headers: dict | None = None,
    text: str = "",
) -> MagicMock:
    """Create a mock requests.Response with the given properties."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.headers = headers or {}
    response.text = text
    response.url = "https://api.github.com/test"
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            response=response
        )
    return response


class TestGetPullRequest:
    @patch.object(requests.Session, "request")
    def test_returns_pr_metadata(self, mock_request: MagicMock, client: GitHubClient) -> None:
        mock_request.return_value = _mock_response(
            json_data={
                "number": 42,
                "title": "Add feature X",
                "user": {"login": "octocat"},
                "base": {"ref": "main"},
                "head": {"ref": "feature-x"},
                "body": "Description here",
                "html_url": "https://github.com/owner/repo/pull/42",
                "changed_files": 3,
                "additions": 50,
                "deletions": 10,
            }
        )

        pr = client.get_pull_request("owner", "repo", 42)
        assert pr.number == 42
        assert pr.title == "Add feature X"
        assert pr.author == "octocat"
        assert pr.base_branch == "main"
        assert pr.head_branch == "feature-x"
        assert pr.changed_files == 3

    @patch.object(requests.Session, "request")
    def test_404_raises_not_found(self, mock_request: MagicMock, client: GitHubClient) -> None:
        mock_request.return_value = _mock_response(status_code=404)
        with pytest.raises(GitHubNotFoundError):
            client.get_pull_request("owner", "repo", 999)

    @patch.object(requests.Session, "request")
    def test_401_raises_auth_error(self, mock_request: MagicMock, client: GitHubClient) -> None:
        mock_request.return_value = _mock_response(status_code=401)
        with pytest.raises(GitHubAuthError):
            client.get_pull_request("owner", "repo", 42)


class TestGetPRFiles:
    @patch.object(requests.Session, "request")
    def test_returns_file_changes(self, mock_request: MagicMock, client: GitHubClient) -> None:
        mock_request.return_value = _mock_response(
            json_data=[
                {
                    "filename": "app.py",
                    "status": "modified",
                    "patch": "@@ -1,3 +1,4 @@\n+import os",
                    "additions": 1,
                    "deletions": 0,
                },
                {
                    "filename": "test.py",
                    "status": "added",
                    "patch": "+def test(): pass",
                    "additions": 1,
                    "deletions": 0,
                },
            ],
            headers={},
        )

        files = client.get_pr_files("owner", "repo", 42)
        assert len(files) == 2
        assert files[0].filename == "app.py"
        assert files[1].status == "added"


class TestPagination:
    @patch.object(requests.Session, "request")
    def test_follows_next_link(self, mock_request: MagicMock, client: GitHubClient) -> None:
        page1 = _mock_response(
            json_data=[{"filename": "a.py", "patch": "+x"}],
            headers={"Link": '<https://api.github.com/page2>; rel="next"'},
        )
        page2 = _mock_response(
            json_data=[{"filename": "b.py", "patch": "+y"}],
            headers={},
        )
        mock_request.side_effect = [page1, page2]

        files = client.get_pr_files("owner", "repo", 1)
        assert len(files) == 2
        assert mock_request.call_count == 2


class TestRateLimit:
    @patch.object(requests.Session, "request")
    @patch("ai_code_reviewer.github_client.time.sleep")
    def test_rate_limit_triggers_wait(
        self, mock_sleep: MagicMock, mock_request: MagicMock, client: GitHubClient
    ) -> None:
        rate_limited = _mock_response(
            status_code=403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "9999999999",
            },
        )
        mock_request.return_value = rate_limited

        with pytest.raises(GitHubRateLimitError):
            client.get_pull_request("owner", "repo", 42)

        mock_sleep.assert_called_once()


class TestParseLinkHeader:
    def test_extracts_next_url(self) -> None:
        response = _mock_response(
            headers={
                "Link": '<https://api.github.com/page2>; rel="next", '
                '<https://api.github.com/page5>; rel="last"'
            }
        )
        url = GitHubClient._parse_next_link(response)
        assert url == "https://api.github.com/page2"

    def test_returns_none_when_no_next(self) -> None:
        response = _mock_response(headers={"Link": '<https://api.github.com/page1>; rel="prev"'})
        url = GitHubClient._parse_next_link(response)
        assert url is None

    def test_returns_none_when_no_link_header(self) -> None:
        response = _mock_response(headers={})
        url = GitHubClient._parse_next_link(response)
        assert url is None
