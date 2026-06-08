# AI News Aggregator

A fully automated, personalized AI news digest system that scrapes content from multiple sources, processes it through a multi-agent LLM pipeline, and delivers a ranked email digest daily — with zero manual intervention and zero infrastructure cost.

The pipeline runs on GitHub Actions on a daily cron schedule. Each run spins up a fresh PostgreSQL container, scrapes the latest AI news, generates LLM summaries and relevance rankings personalized to a user profile, and sends a formatted HTML email — then the environment is torn down cleanly.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Pipeline Stages](#pipeline-stages)
- [Agent Design](#agent-design)
- [Data Sources](#data-sources)
- [Database Schema](#database-schema)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [GitHub Actions Deployment](#github-actions-deployment)
- [Configuration](#configuration)
- [Docker](#docker)
- [Rate Limiting](#rate-limiting)
- [Adding New Sources](#adding-new-sources)

---

## Overview

The system aggregates AI news from three sources — the OpenAI blog, Anthropic blog (news, research, and engineering feeds), and a YouTube channel — on a 5-day rolling window. Each article is processed through a 5-stage pipeline:

1. Scrape raw articles and store them in PostgreSQL
2. Enrich content (convert Anthropic HTML pages to Markdown, fetch YouTube transcripts)
3. Generate a concise digest (title + 2-3 sentence summary) for each article via an LLM
4. Rank all digests by relevance to the user's profile and interests using a curator LLM
5. Generate a personalized email introduction and send the top-N digest as a formatted HTML email

The entire pipeline is stateless — each GitHub Actions run creates fresh tables, processes all content in the lookback window, and delivers the email. There is no persistent server or long-running process.

---

## Architecture

```
GitHub Actions (cron: daily at 8 AM UTC)
        |
        v
PostgreSQL (ephemeral service container)
        |
        v
[1] Scrapers
    - OpenAI RSS (feedparser)
    - Anthropic RSS x3 (feedparser) + HTML-to-Markdown (docling)
    - YouTube RSS (feedparser) + Transcripts (youtube-transcript-api)
        |
        v
[2] Content Enrichment
    - Anthropic articles: full page converted to Markdown
    - YouTube videos: transcript fetched and stored
        |
        v
[3] DigestAgent  (Gemini API)
    - Generates title + summary for each article
    - Structured output via Pydantic v2
        |
        v
[4] CuratorAgent  (Gemini API)
    - Scores each digest 0.0-10.0 by relevance to user profile
    - Returns ranked list with reasoning per article
        |
        v
[5] EmailAgent  (Gemini API)
    - Generates personalized greeting and introduction
    - Composes final EmailDigestResponse
        |
        v
Gmail SMTP (HTML + plain text multipart email)
```

---

## Pipeline Stages

### Stage 1 — Scraping

Three scrapers run in sequence and persist results to PostgreSQL. Duplicate detection uses the article GUID (RSS `<id>`) as a primary key — re-running the pipeline on the same window will not create duplicate rows.

- **OpenAIScraper**: Parses `https://openai.com/news/rss.xml`. Filters entries published within the configured time window.
- **AnthropicScraper**: Parses three community-maintained RSS mirrors covering Anthropic news, research, and engineering. Deduplicates across feeds by GUID.
- **YouTubeScraper**: Parses the YouTube RSS feed for a given channel ID. Skips Shorts (`/shorts/` in the URL). Fetches full video transcripts using `youtube-transcript-api`.

### Stage 2 — Content Enrichment

- **Anthropic Markdown**: Anthropic RSS entries contain only short descriptions. The scraper fetches the full article page and converts it to Markdown using `docling` (`DocumentConverter`). This provides the digest agent with full article context rather than a snippet.
- **YouTube Transcripts**: Transcripts are fetched per video ID. Videos with disabled transcripts are marked `__UNAVAILABLE__` and excluded from digest generation.

### Stage 3 — Digest Generation (DigestAgent)

For each article that does not yet have a digest, `DigestAgent` calls the Gemini API and returns a structured `DigestOutput`:

```python
class DigestOutput(BaseModel):
    title: str    # 5-10 word rewritten title
    summary: str  # 2-3 sentence summary
```

Content is truncated to 8,000 characters before being sent to the API. A 4-second sleep is applied before each call to respect the 15 RPM free-tier rate limit.

### Stage 4 — Curation and Ranking (CuratorAgent)

All digests from the lookback window are sent in a single API call to `CuratorAgent`. The agent scores each digest against the user profile and returns a `RankedDigestList`:

```python
class RankedArticle(BaseModel):
    digest_id: str
    relevance_score: float  # 0.0 to 10.0
    rank: int
    reasoning: str
```

The system prompt embeds the full user profile (name, background, interests, preferences, expertise level) so rankings are personalized, not generic.

### Stage 5 — Email Generation and Delivery (EmailAgent + Gmail SMTP)

`EmailAgent` generates a personalized greeting and introduction paragraph that previews the top articles. The `EmailDigestResponse` is rendered as both HTML and plain text:

- **HTML**: Styled with inline CSS, article titles as `<h3>`, summaries as `<div>`, and "Read more" links.
- **Plain text**: Markdown format as fallback for email clients that do not render HTML.

The email is sent via `smtplib.SMTP_SSL` on port 465 using a Gmail App Password.

---

## Agent Design

All three agents are intentionally self-contained — each holds its own `OpenAI` client instance, model name, and rate-limit constant. This makes them independently deployable as separate microservices without refactoring.

| Agent | Temperature | Role |
|-------|-------------|------|
| DigestAgent | 0.7 | Summarization — creative but factual |
| CuratorAgent | 0.3 | Ranking — deterministic, consistent scoring |
| EmailAgent | 0.7 | Writing — warm, personalized tone |

All agents use the Gemini API via its OpenAI-compatible endpoint:

```
https://generativelanguage.googleapis.com/v1beta/openai/
```

Structured outputs are parsed using `Model.model_validate_json()` on the raw response string. The `response_format={"type": "json_object"}` parameter is set on every request to enforce JSON output from the model.

---

## Data Sources

| Source | Method | Feed |
|--------|--------|------|
| OpenAI Blog | RSS via feedparser | `https://openai.com/news/rss.xml` |
| Anthropic News | RSS via feedparser | Community RSS mirror |
| Anthropic Research | RSS via feedparser | Community RSS mirror |
| Anthropic Engineering | RSS via feedparser | Community RSS mirror |
| YouTube Channel | RSS + Transcript API | Configurable channel ID in `config.py` |

Default YouTube channel: Matthew Berman (`UCawZsQWqfGSbCI5yjkdVkTA`). Multiple channels are supported — add additional IDs to the `YOUTUBE_CHANNELS` list in `config.py`.

---

## Database Schema

Four tables are managed via SQLAlchemy ORM. The schema is ephemeral in the GitHub Actions context — tables are recreated fresh on every run.

**youtube_videos**

| Column | Type | Notes |
|--------|------|-------|
| video_id | String (PK) | YouTube video ID |
| title | String | Video title |
| url | String | Watch URL |
| channel_id | String | Source channel |
| published_at | DateTime | UTC publish time |
| description | Text | RSS description |
| transcript | Text | Full transcript or `__UNAVAILABLE__` |
| created_at | DateTime | Row insertion time |

**openai_articles**

| Column | Type | Notes |
|--------|------|-------|
| guid | String (PK) | RSS entry ID |
| title | String | Article title |
| url | String | Article URL |
| description | Text | RSS description snippet |
| published_at | DateTime | UTC publish time |
| category | String | RSS tag/category if present |
| created_at | DateTime | Row insertion time |

**anthropic_articles**

| Column | Type | Notes |
|--------|------|-------|
| guid | String (PK) | RSS entry ID |
| title | String | Article title |
| url | String | Article URL |
| description | Text | RSS description snippet |
| published_at | DateTime | UTC publish time |
| category | String | RSS tag/category if present |
| markdown | Text | Full page converted to Markdown via docling |
| created_at | DateTime | Row insertion time |

**digests**

| Column | Type | Notes |
|--------|------|-------|
| id | String (PK) | Composite key: `article_type:article_id` |
| article_type | String | `youtube`, `openai`, or `anthropic` |
| article_id | String | Source table primary key |
| url | String | Original article URL |
| title | String | LLM-generated title |
| summary | Text | LLM-generated 2-3 sentence summary |
| created_at | DateTime | Used for the rolling lookback window query |

---

## Project Structure

```
.
├── main.py                        # Entry point — accepts hours and top_n args
├── pyproject.toml                 # Project dependencies managed by uv
├── uv.lock                        # Locked dependency versions
├── Dockerfile                     # Container image definition
├── entrypoint.sh                  # Docker container startup script
├── .env                           # Local environment secrets (gitignored)
├── .github/
│   └── workflows/
│       └── daily_digest.yml       # GitHub Actions cron workflow
└── app/
    ├── config.py                  # YOUTUBE_CHANNELS and USER_PROFILE
    ├── daily_runner.py            # 5-stage pipeline orchestrator
    ├── agent/
    │   ├── digest_agent.py        # Summarization agent (DigestAgent)
    │   ├── curator_agent.py       # Ranking agent (CuratorAgent)
    │   └── email_agent.py         # Email agent + data models
    ├── database/
    │   ├── models.py              # SQLAlchemy ORM table definitions
    │   ├── connection.py          # Engine, session factory, create_tables()
    │   └── repository.py          # All database read/write operations
    ├── scrapers/
    │   ├── openai.py              # OpenAI RSS scraper
    │   ├── anthropic.py           # Anthropic RSS scraper + docling converter
    │   └── youtube.py             # YouTube RSS scraper + transcript fetcher
    └── services/
        ├── pipeline.py            # Enrichment and digest processing functions
        └── email.py               # Email rendering, sending, and digest orchestration
```

---

## Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python 3.12 |
| Package Manager | uv |
| LLM | Google Gemini (`gemini-3.1-flash-lite`) via OpenAI-compatible endpoint |
| LLM Client | openai SDK |
| Structured Output | Pydantic v2 (`model_validate_json`) |
| Database | PostgreSQL 17 |
| ORM | SQLAlchemy 2.x |
| RSS Parsing | feedparser |
| HTML-to-Markdown | docling (`DocumentConverter`) |
| YouTube Transcripts | youtube-transcript-api |
| Email Delivery | smtplib — Gmail SMTP SSL on port 465 |
| HTML Email Rendering | markdown (Python library) |
| CI/CD | GitHub Actions |
| Containerization | Docker |
| Environment Config | python-dotenv |

---

## Local Setup

### Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for running PostgreSQL locally)
- A Google Gemini API key (free tier is sufficient)
- A Gmail account with an App Password configured

### Steps

**1. Clone the repository**

```bash
git clone https://github.com/shreyaschhabra/ai-news-aggregator.git
cd ai-news-aggregator
```

**2. Install dependencies**

```bash
uv sync
```

**3. Start PostgreSQL locally**

```bash
docker run -d \
  --name ai-news-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=ai_news_aggregator \
  -p 5432:5432 \
  postgres:17
```

**4. Create the `.env` file**

Copy the template and fill in your credentials (see [Environment Variables](#environment-variables)):

```bash
cp .env.example .env
```

**5. Create database tables**

```bash
uv run python -m app.database.connection
```

**6. Run the pipeline**

```bash
# 5-day lookback window, top 10 articles in email
uv run python main.py 120 10

# Custom: 48-hour window, top 5 articles
uv run python main.py 48 5
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here

# Gmail SMTP
MY_EMAIL=your.email@gmail.com
APP_PASSWORD=xxxx xxxx xxxx xxxx

# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=ai_news_aggregator
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

**Gmail App Password setup:**
1. Enable 2-Step Verification on your Google account
2. Go to Google Account > Security > App Passwords
3. Generate a new App Password for "Mail"
4. Use the 16-character result as `APP_PASSWORD` (spaces are fine)

**Gemini API key setup:**
1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Create a new API key
3. The free tier (`gemini-3.1-flash-lite`) allows 15 RPM and 500 RPD — sufficient for daily runs

**Alternative database URL:**

If `DATABASE_URL` is set, it takes precedence over the individual `POSTGRES_*` variables. Use this for managed PostgreSQL providers:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

---

## GitHub Actions Deployment

The workflow in `.github/workflows/daily_digest.yml` runs every day at 8:00 AM UTC and can also be triggered manually via the GitHub Actions UI (`workflow_dispatch`).

### Required GitHub Secrets

Go to **Settings > Secrets and variables > Actions** in your repository and add:

| Secret | Description |
|--------|-------------|
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `MY_EMAIL` | The Gmail address to send the digest from and to |
| `APP_PASSWORD` | Your Gmail App Password |

### How the Workflow Runs

1. Checks out the repository at the latest commit on `main`
2. Installs `uv` via `astral-sh/setup-uv@v6`
3. Installs Python dependencies with `uv sync --frozen --no-dev`
4. Starts a `postgres:17` service container with a health check before proceeding
5. Creates all database tables via `python -m app.database.connection`
6. Runs the full pipeline: `python main.py 120 10`
7. Job completes — the PostgreSQL container and all data are destroyed

The pipeline is fully stateless. No data persists between runs. Every execution starts with a clean database and processes all articles published in the last 5 days.

---

## Configuration

### User Profile

The user profile in `app/config.py` is embedded verbatim into the `CuratorAgent` system prompt. Edit it to change how articles are ranked for you:

```python
USER_PROFILE = {
    "name": "Shreyas",
    "title": "AI Student",
    "background": "AI engineer student with deep interest in practical AI applications...",
    "interests": [
        "Large Language Models (LLMs) and their applications",
        "Retrieval-Augmented Generation (RAG) systems",
        "AI agent architectures and frameworks",
        "Multimodal AI and vision-language models",
        "AI safety and alignment research",
        "Production AI systems and MLOps",
        "Real-world AI applications and case studies",
        "Technical tutorials and implementation guides",
        "Research papers with practical implications",
        "AI infrastructure and scaling challenges",
    ],
    "preferences": {
        "prefer_practical": True,
        "prefer_technical_depth": True,
        "prefer_research_breakthroughs": True,
        "prefer_production_focus": True,
        "avoid_marketing_hype": True,
    },
    "expertise_level": "Advanced",
}
```

### YouTube Channels

Add additional channel IDs to `YOUTUBE_CHANNELS` in `app/config.py`:

```python
YOUTUBE_CHANNELS = [
    "UCawZsQWqfGSbCI5yjkdVkTA",  # Matthew Berman
]
```

The scraper will query the RSS feed for each channel ID and aggregate results.

### Lookback Window and Top N

Controlled via command-line arguments to `main.py`:

```
python main.py <hours> <top_n>
```

- `hours`: How far back to scrape (default: 120 hours / 5 days). A 5-day window is used to ensure a consistent volume of articles — a 24-hour window frequently yields too few articles depending on publishing schedules.
- `top_n`: Number of top-ranked articles to include in the email (default: 10).

---

## Docker

A `Dockerfile` is provided for containerized deployment.

```bash
# Build the image
docker build -t ai-news-aggregator .

# Run with your .env file
docker run --env-file .env ai-news-aggregator
```

On startup, `entrypoint.sh` runs:
1. `python -m app.database.connection` — creates tables
2. `python main.py 24 10` — runs the pipeline with a 24-hour window

The Dockerfile copies the `uv` binary from `ghcr.io/astral-sh/uv` for fast, reproducible installs using the locked `uv.lock` file.

The container requires an external PostgreSQL instance configured via environment variables. It does not bundle a database.

---

## Rate Limiting

The Gemini free tier for `gemini-3.1-flash-lite` enforces:

- 15 requests per minute (RPM)
- 500 requests per day (RPD)

Each agent applies a 4-second sleep before every API call (`time.sleep(4)`), keeping throughput at exactly 15 RPM without bursting. For a pipeline run processing N articles, the total number of Gemini API calls is:

```
N  (one digest per article)
+1 (one ranking call for all digests)
+1 (one email introduction call)
= N + 2 calls per run
```

For a typical 5-day window, this is well within the 500 RPD daily quota.

---

## Adding New Sources

To add a new content source:

**1. Create a scraper** in `app/scrapers/` following the pattern in `openai.py`. Return a list of Pydantic models with at minimum `title`, `url`, `guid`, `published_at`, and `description`.

**2. Add a database model** in `app/database/models.py` extending `Base`.

**3. Add repository methods** in `app/database/repository.py`:
- A `bulk_create_*` method for inserting new rows
- Include the new table in `get_articles_without_digest` so its content enters the digest pipeline

**4. Wire the scraper into the pipeline** in `app/daily_runner.py` inside `_scrape_and_save`.

The digest, curation, and email stages require no changes — they operate on the unified `digests` table regardless of which source an article came from.
