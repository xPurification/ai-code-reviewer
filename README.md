# AI Code Review Assistant

A production-grade CLI tool that performs automated code reviews using **Google Gemini** and the **GitHub API**. It analyzes pull requests and local codebases for bugs, security vulnerabilities, performance risks, code quality issues, and best practice violations — producing structured, actionable reports suitable for real engineering workflows.

---

## Architecture

```
ai_code_reviewer/
│
├── ai_code_reviewer/           # Core package
│   ├── __init__.py             # Package metadata
│   ├── cli.py                  # Click CLI commands and argument parsing
│   ├── config.py               # Environment-based configuration management
│   ├── github_client.py        # GitHub REST API client with retry + pagination
│   ├── gemini_client.py        # Google Gemini API client with structured prompts
│   ├── review_engine.py        # Review pipeline orchestration
│   ├── diff_parser.py          # Unified diff format parser
│   ├── report.py               # Rich terminal reports and JSON export
│   ├── models.py               # Pydantic data models
│   └── logging_config.py       # Structured logging with Rich
│
├── tests/                      # pytest test suite
│   ├── test_review_engine.py   # Review pipeline and scoring tests
│   ├── test_github_client.py   # API client, pagination, error handling tests
│   └── test_diff_parser.py     # Diff parsing and hunk extraction tests
│
├── pyproject.toml              # PEP 621 package configuration
├── requirements.txt            # Pinned dependencies
├── .env.example                # Environment variable template
├── main.py                     # CLI entry point
└── README.md
```

### Data Flow

```
┌──────────┐     ┌──────────────┐     ┌───────────────┐
│  CLI     │────▶│ ReviewEngine │────▶│ GeminiClient  │
│ (Click)  │     │              │     │ (Gemini API)  │
└──────────┘     │              │     └───────────────┘
     │           │              │
     │           │              │     ┌───────────────┐
     │           │              │────▶│ GitHubClient  │
     │           │              │     │ (GitHub API)  │
     │           └──────────────┘     └───────────────┘
     │                  │
     ▼                  ▼
┌──────────┐     ┌──────────────┐
│  Report  │◀────│   Models     │
│  (Rich)  │     │  (Pydantic)  │
└──────────┘     └──────────────┘
```

---

## Features

- **Pull Request Reviews** — Fetch and analyze GitHub PRs with a single command
- **Local Directory Scanning** — Review entire codebases without pushing to GitHub
- **Single File Analysis** — Quick review of individual source files
- **Security-Focused Analysis** — Explicit checks for injection, secrets, auth flaws, unsafe deserialization
- **Structured Scoring** — Severity-weighted quality score (0–100) with category breakdowns
- **Rich Terminal Reports** — Color-coded tables, progress bars, executive summaries
- **JSON Export** — Machine-readable output for CI/CD integration
- **Retry & Rate Limiting** — Exponential backoff with tenacity, GitHub rate-limit awareness
- **Pagination** — Automatic handling of large PRs with many changed files
- **Configurable** — All settings via environment variables or `.env` files

---

## Installation

### Prerequisites

- Python 3.11 or higher
- A [Google Gemini API key](https://aistudio.google.com/apikey)
- A [GitHub personal access token](https://github.com/settings/tokens) (for PR reviews)

### Install from Source

```bash
git clone https://github.com/your-username/ai-code-reviewer.git
cd ai-code-reviewer
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

---

## CLI Usage

### Review a Pull Request

```bash
ai-review review-pr --repo owner/repo --pr-number 42
```

With JSON output:

```bash
ai-review review-pr --repo owner/repo --pr-number 42 --output json
```

### Review a Local Directory

```bash
ai-review review-local --path ./src
```

### Review a Single File

```bash
ai-review review-file --path ./app/main.py
```

### Show Configuration

```bash
ai-review config show
```

### Enable Debug Logging

```bash
ai-review -v review-pr --repo owner/repo --pr-number 42
```

---

## Sample Output

```
╭──────────────────────────────────────────────────────────╮
│             AI Code Review Assistant                     │
│     Automated analysis powered by Google Gemini          │
╰──────────────────────────────────────────────────────────╯
╭─ Executive Summary ──────────────────────────────────────╮
│ The codebase has several security and maintainability    │
│ issues that should be addressed before production.       │
│                                                          │
│ 6 issue(s) found | 1 critical | 2 high                  │
╰──────────────────────────────────────────────────────────╯
╭─ Quality Score ──────────────────────────────────────────╮
│ Score: 45/100 — Needs Improvement                        │
│ ██████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
╰──────────────────────────────────────────────────────────╯
┏━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Sev ┃ Category    ┃ Location       ┃ Description       ┃
┡━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│CRIT │ security    │ auth.py:42     │ SQL injection via │
│     │             │                │ f-string query    │
│HIGH │ bug         │ handler.py:87  │ Uncaught          │
│     │             │                │ NoneType access   │
│MED  │ performance │ db.py:15       │ N+1 query pattern │
│LOW  │ style       │ utils.py:3     │ Unused import     │
└─────┴─────────────┴────────────────┴───────────────────┘
```

---

## Design Decisions

| Decision | Rationale |
|---|---|
| **Pydantic for all data models** | Type-safe validation at API boundaries; automatic JSON serialization |
| **Tenacity for retries** | Battle-tested retry library with configurable backoff strategies |
| **Dependency injection** | ReviewEngine accepts clients as parameters for easy testing |
| **StrEnum for categories** | Type safety combined with string serialization for JSON output |
| **Lazy API key validation** | Keys are only required when the corresponding API is actually called |
| **Subtractive scoring** | Starts at 100, deducts severity-weighted penalties — intuitive and deterministic |
| **File-boundary chunking** | Splits large PRs at file boundaries first, preserving context within files |
| **Rich for terminal output** | Professional formatting with color-coded severity and structured tables |
| **Click for CLI** | Declarative command definition with automatic help generation |
| **Structured logging** | Rich console handler for development; easily extended with JSON file handlers |

---

## Running Tests

```bash
pytest -v
```

Run with coverage:

```bash
pytest --cov=ai_code_reviewer --cov-report=term-missing
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | For PR reviews | — | GitHub personal access token |
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model to use |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `MAX_FILE_SIZE` | No | `50000` | Max file size in characters |
| `REQUEST_TIMEOUT` | No | `30` | API request timeout in seconds |
| `MAX_RETRIES` | No | `3` | Maximum API retry attempts |

---

## Future Improvements

- **GitLab and Bitbucket support** — extend the VCS client interface beyond GitHub
- **Inline PR comments** — post review issues directly as GitHub PR review comments
- **Custom rule configuration** — allow teams to define custom review rules and severity mappings
- **Caching layer** — cache Gemini responses to avoid re-reviewing unchanged files
- **Parallel chunk analysis** — send multiple chunks concurrently for faster large-PR reviews
- **Pre-commit hook integration** — run reviews automatically before commits
- **CI/CD pipeline action** — GitHub Action for automated PR review in CI
- **Historical trend tracking** — track code quality scores over time per repository
- **Multi-language prompt tuning** — optimize review prompts per programming language

---

## Resume Bullet

> Built a production CLI tool in Python that automates code reviews using Google Gemini and the GitHub API, featuring structured security analysis, severity-scored reporting with Rich terminal output, retry-resilient API clients, and a modular architecture with dependency injection and comprehensive test coverage.

---

## License

MIT
