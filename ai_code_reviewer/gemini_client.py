"""Google Gemini API client for AI-powered code analysis.

Handles prompt construction, structured JSON response parsing, input chunking,
and retry logic for transient API failures.  Uses the ``google-genai`` SDK.
"""

from __future__ import annotations

import json
import re
from typing import Any

from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ai_code_reviewer.logging_config import get_logger

logger = get_logger(__name__)

SYSTEM_INSTRUCTION = """\
You are an expert senior software engineer performing a thorough code review.
Analyze the provided code for:

1. **Bugs and Logic Errors**: Off-by-one errors, null/None dereferences, \
incorrect conditionals, race conditions, unhandled edge cases.
2. **Security Vulnerabilities**: Injection attacks (SQL, command, XSS), \
unsafe deserialization, hardcoded secrets/credentials, insecure cryptography, \
authentication/authorization flaws, path traversal.
3. **Performance Issues**: Unnecessary allocations, O(n^2) algorithms where \
O(n) is possible, missing caching opportunities, blocking I/O in async code, \
N+1 query patterns.
4. **Code Quality & Maintainability**: Dead code, excessive complexity, \
poor naming, missing error handling, tight coupling, violations of DRY/SOLID.
5. **Best Practice Violations**: Missing type hints, inconsistent style, \
deprecated API usage, missing input validation, poor logging practices.

You MUST respond with valid JSON matching this exact schema:

{
  "summary": "Brief overall assessment of the code quality",
  "overall_score": <integer 0-100>,
  "issues": [
    {
      "severity": "low|medium|high|critical",
      "category": "bug|security|performance|style|maintainability",
      "file": "filename or path",
      "line": <line number or null>,
      "description": "Clear description of the issue",
      "recommendation": "Specific actionable fix",
      "confidence": <float 0.0-1.0>
    }
  ]
}

Rules:
- Set overall_score based on issue count and severity (100 = perfect, 0 = critical failures).
- Only report real issues with specific evidence from the code.
- Provide concrete, actionable recommendations, not vague suggestions.
- Set confidence based on how certain you are the issue is real.
- If the code looks clean, return an empty issues array with a high score.
- Do NOT wrap the JSON in markdown code fences.
"""


class GeminiClientError(Exception):
    """Base exception for Gemini client errors."""


class GeminiResponseError(GeminiClientError):
    """Raised when the Gemini response cannot be parsed as valid JSON."""


class GeminiClient:
    """Client for performing code analysis via the Google Gemini API.

    Args:
        api_key: Google Gemini API key.
        model_name: Gemini model identifier.
        max_retries: Maximum retry attempts for transient failures.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        self._max_retries = max_retries
        self._timeout = timeout
        self._model_name = model_name
        self._client = genai.Client(api_key=api_key)
        logger.info("Gemini client initialized with model: %s", model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    @retry(
        retry=retry_if_exception_type(
            (
                google_exceptions.ServiceUnavailable,
                google_exceptions.InternalServerError,
                google_exceptions.ResourceExhausted,
                google_exceptions.DeadlineExceeded,
            )
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def analyze_code(self, prompt: str, code: str) -> dict[str, Any]:
        """Send code to Gemini for analysis and return structured results.

        Args:
            prompt: Context and instructions for the review.
            code: The source code or diff to analyze.

        Returns:
            Parsed JSON response matching the review schema.

        Raises:
            GeminiResponseError: If the response is not valid JSON.
            GeminiClientError: For unrecoverable API errors.
        """
        full_prompt = f"{prompt}\n\n```\n{code}\n```"
        logger.debug(
            "Sending analysis request (%d chars prompt, %d chars code)",
            len(prompt),
            len(code),
        )

        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.1,
                    response_mime_type="application/json",
                    http_options=types.HttpOptions(timeout=self._timeout * 1000),
                ),
            )
        except google_exceptions.InvalidArgument as exc:
            raise GeminiClientError(f"Invalid request to Gemini API: {exc}") from exc
        except google_exceptions.PermissionDenied as exc:
            raise GeminiClientError(
                "Gemini API key is invalid or lacks permissions."
            ) from exc

        return self._parse_response(response)

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Extract and validate JSON from the Gemini response."""
        if not response.candidates:
            raise GeminiResponseError("Gemini returned no candidates.")

        text = response.text.strip()
        json_str = self._extract_json(text)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini response as JSON: %s", text[:500])
            raise GeminiResponseError(
                f"Invalid JSON in Gemini response: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise GeminiResponseError(
                f"Expected JSON object, got {type(parsed).__name__}"
            )

        required_keys = {"summary", "overall_score", "issues"}
        missing = required_keys - parsed.keys()
        if missing:
            raise GeminiResponseError(f"Missing required keys: {missing}")

        return parsed

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences if the model wraps its JSON output."""
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def chunk_content(content: str, max_chars: int = 40_000) -> list[str]:
        """Split large content into chunks at logical boundaries.

        Tries to split at class/function definitions first, then falls back
        to splitting at blank lines, and finally at the character limit.

        Args:
            content: The full content string to chunk.
            max_chars: Maximum characters per chunk.

        Returns:
            List of content chunks, each within the size limit.
        """
        if len(content) <= max_chars:
            return [content]

        chunks: list[str] = []
        lines = content.split("\n")
        current_chunk: list[str] = []
        current_size = 0

        boundary_patterns = re.compile(
            r"^(class\s+|def\s+|async\s+def\s+|function\s+|export\s+)"
        )

        for line in lines:
            line_size = len(line) + 1
            is_boundary = bool(boundary_patterns.match(line.strip()))

            if current_size + line_size > max_chars and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            elif is_boundary and current_size > max_chars * 0.3 and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0

            current_chunk.append(line)
            current_size += line_size

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        logger.info("Split content into %d chunks", len(chunks))
        return chunks
