# Job Discovery Engine

AI-assisted job discovery with verified results. The system uses Google Gemini 2.5 Flash with Google Search grounding to find real job postings from primary sources, then pushes each candidate URL through a fail-fast verification pipeline before storing verified institutions, jobs, and audit evidence in PostgreSQL.

## What This Does

1. You submit a search query such as `AI safety research labs hiring`.
2. Gemini performs grounded web search and returns structured institution/job candidates.
3. Every institution careers URL goes through five verification checks.
4. Verified institutions and jobs are upserted into PostgreSQL.
5. A React dashboard lets you inspect search runs, evidence, and stored entities.

## Architecture

```text
┌──────────────────┐     ┌──────────────────────┐     ┌──────────────────────────┐
│ React UI         │────▶│ FastAPI Backend      │────▶│ PostgreSQL 16            │
│ localhost:3000   │◀────│ localhost:8000       │◀────│ container:5432           │
│ Dashboard +      │     │ API + Orchestrator   │     │ host:5433                │
│ detail views     │     │ + Verification       │     │ institutions / jobs /    │
└──────────────────┘     └──────────┬───────────┘     │ search_runs / evidence    │
                                    │                 └──────────────────────────┘
                         ┌──────────▼───────────┐
                         │ Gemini 2.5 Flash     │
                         │ + Google Search      │
                         │ Grounding            │
                         └──────────────────────┘

Search pipeline:
query
  → build prompt with known domains
  → Gemini grounded search
  → parse structured JSON response
  → verify candidate careers URLs
  → upsert institutions and jobs
  → persist verification evidence and run metrics
```

## Repository Layout

```text
job-discovery-engine/
├── backend/
│   ├── app/api/              # FastAPI routes
│   ├── app/services/         # Gemini, parsing, verification, orchestration
│   ├── app/models/           # SQLModel entities and candidate schemas
│   ├── app/core/             # Config, DB, logging, URL utilities
│   ├── alembic/              # Database migrations
│   └── tests/                # API, service, and pipeline tests
├── frontend/
│   ├── src/pages/            # Dashboard and detail pages
│   ├── src/components/       # Search form and shared UI
│   └── src/api.ts            # Axios client
├── docker-compose.yml        # Local PostgreSQL service
└── .env.example              # Required environment variables
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker with Docker Compose
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

### Setup

1. Clone the repository and enter it:

   ```bash
   git clone <your-repo-url>
   cd job-discovery-engine
   ```

2. Create your environment file:

   ```bash
   cp .env.example .env
   ```

3. Edit `.env` and set `GEMINI_API_KEY`.

4. Start PostgreSQL:

   ```bash
   docker compose up -d postgres
   ```

   The database container listens on `5432` internally and is published on `localhost:5433` to avoid conflicts with an existing local Postgres install.

5. Set up the backend:

   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   alembic upgrade head
   ```

6. Set up the frontend:

   ```bash
   cd ../frontend
   npm install
   ```

### Run

Start the backend in one terminal:

```bash
cd job-discovery-engine/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Start the frontend in a second terminal:

```bash
cd job-discovery-engine/frontend
npm start
```

Then open:

- Frontend: [http://localhost:3000](http://localhost:3000)
- API root: [http://localhost:8000/](http://localhost:8000/)
- API health: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- FastAPI docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Smoke Test

Trigger a run with curl:

```bash
curl -X POST http://localhost:8000/api/search-runs \
  -H 'Content-Type: application/json' \
  -d '{"query":"AI safety research labs hiring researchers"}'
```

Useful follow-up checks:

```bash
curl http://localhost:8000/api/search-runs?limit=5
curl http://localhost:8000/api/institutions?verified=true
curl http://localhost:8000/api/jobs?is_active=true
```

## Environment

The repo-level `.env` drives both backend and frontend development defaults.

| Variable | Required | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes | API key used by the Google GenAI SDK |
| `DATABASE_URL` | Yes | Async SQLAlchemy URL, defaulting to local Compose Postgres on `localhost:5433` |
| `ENVIRONMENT` | No | Preferred runtime environment name, used to default logs to `readable` in development and `json` in production |
| `APP_ENV` | No | Legacy alias for `ENVIRONMENT`, only read when `ENVIRONMENT` is unset |
| `LOG_LEVEL` | No | Application log level |
| `LOG_FORMAT` | No | Log formatter override: `readable` or `json`; leave unset to use the `ENVIRONMENT`-based default |
| `VERIFICATION_TIMEOUT_SECONDS` | No | Per-URL timeout for verification checks |
| `REACT_APP_API_URL` | No | Frontend override for the backend base URL |

Default local database URL:

```text
postgresql+asyncpg://jobengine@localhost:5433/jobengine
```

## API Reference

### `POST /api/search-runs`

Trigger a new search run and wait for the full pipeline to finish.

- Body:

  ```json
  {
    "query": "AI safety research labs hiring researchers"
  }
  ```

- Returns: run summary with counts for raw candidates, verified candidates, upsert totals, duration, and error details.

### `GET /api/search-runs`

List recent search runs in descending `initiated_at` order.

- Query parameters:
  - `limit` optional, default `100`, capped at `500`

### `GET /api/search-runs/{run_id}`

Return full detail for a single search run.

- Includes:
  - run timestamps and status
  - raw Gemini response text
  - all verification evidence records ordered by `checked_at`

### `GET /api/institutions`

List stored institutions with optional filters.

- Query parameters:
  - `verified` optional boolean filter
  - `type` optional institution type such as `university`, `company`, or `research_lab`
  - `limit` optional, default `100`, capped at `500`

### `GET /api/institutions/{institution_id}`

Return a single institution plus all associated jobs sorted by most recent activity.

### `GET /api/jobs`

List stored jobs with optional filters.

- Query parameters:
  - `is_active` optional boolean filter
  - `experience_level` optional value such as `intern`, `entry`, `mid`, `senior`, `lead`, or `executive`
  - `limit` optional, default `100`, capped at `500`

### `GET /api/health`

Return lightweight service readiness data.

- Response fields:
  - `status`
  - `service`
  - `version`
  - `gemini_api_key_configured`
  - `database_url_configured`

## Verification Pipeline

Each candidate careers URL moves through a fail-fast five-check pipeline. The pipeline stops on the first failure, but every attempted check is recorded in `verification_evidence` for auditability.

1. `url_wellformed`: validates scheme, hostname, TLD, port, and hostname label syntax.
2. `not_aggregator`: rejects job boards and ATS/aggregator domains so only primary sources remain.
3. `dns_resolves`: confirms the hostname has live DNS records.
4. `http_reachable`: performs an HTTP GET with redirects enabled and expects a `200-399` response.
5. `content_signals`: scans the response body for careers/job keywords and requires enough signals to classify the page as hiring-related.

Implementation notes:

- Checks run from cheapest to most expensive.
- Verification runs in parallel across candidates, with bounded concurrency.
- Search run detail pages expose the evidence matrix so you can inspect pass/fail reasons per candidate.

## Observability

The backend stores both pipeline outcomes and the evidence needed to inspect them later.

- `search_runs` tracks lifecycle state, duration, raw/verified counts, upsert totals, and any error detail.
- `verification_evidence` records every attempted check, pass/fail status, detail text, and duration.
- Request middleware logs every HTTP request with timing metadata.
- Set `LOG_FORMAT=json` to emit one valid JSON object per log line with stable fields such as `timestamp`, `level`, `component`, `message`, `event`, `search_run_id`, and `duration_ms`.
- The frontend exposes three operational views:
  - dashboard summary
  - search run audit trail
  - institution detail with associated jobs

## Why Gemini 2.5 Flash

Gemini 2.5 Flash is a pragmatic fit for this repository because the product problem is retrieval-heavy rather than deep chain-of-thought-heavy.

- The backend can call one model and one SDK for both grounded web search and JSON output.
- Google Search grounding reduces the need for a separate search API integration.
- JSON-mode output fits the parser and candidate schema flow cleanly.
- Flash-class latency and cost characteristics are better suited to repeated discovery runs than a larger reasoning-first model.

In code, the Gemini client uses:

- `model="gemini-2.5-flash"`
- `types.Tool(google_search=types.GoogleSearch())`
- `response_mime_type="application/json"`

## Tech Stack

- Backend: FastAPI, SQLModel, SQLAlchemy async, asyncpg, Alembic
- Database: PostgreSQL 16
- AI: Google Gemini 2.5 Flash via `google-genai`
- Verification: `httpx`, DNS checks via `socket`, URL normalization/blocklists
- Frontend: React, TypeScript, Axios, Recharts
- Local infrastructure: Docker Compose

## Screenshots

Screenshot placeholders for future documentation:

- Dashboard overview showing summary cards, recent runs, and verified institutions
- Search run detail showing the funnel and verification evidence table
- Institution detail showing stored metadata and linked jobs

## Testing

Backend tests can be run with:

```bash
cd backend
source .venv/bin/activate
pytest
```

There is also a live end-to-end curl script at `backend/tests/manual_curl_test.sh` for exercising the running API against a real Gemini-backed search.
