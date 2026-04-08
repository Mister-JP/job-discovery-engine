# Contributing to Job Discovery Engine

This guide assumes you are working from the `job-discovery-engine/` repository root.

## Development Setup

1. Clone the repository and enter it:

   ```bash
   git clone <your-repo-url>
   cd job-discovery-engine
   ```

2. Create your environment file:

   ```bash
   cp .env.example .env
   ```

3. Start PostgreSQL:

   ```bash
   docker compose up -d postgres
   ```

4. Set up the backend:

   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   alembic upgrade head
   ```

5. Set up the frontend:

   ```bash
   cd ../frontend
   npm install
   ```

6. Run the app locally when you need the full stack:

   Backend:

   ```bash
   cd backend
   source .venv/bin/activate
   uvicorn app.main:app --reload --port 8000
   ```

   Frontend:

   ```bash
   cd frontend
   npm start
   ```

## Running Tests

### Backend unit tests (no network, no database)

Use these for fast feedback on parsing, URL validation, prompt building, and
verification logic.

```bash
cd backend
source .venv/bin/activate
pytest tests/test_url_utils.py tests/test_verification_checks.py tests/test_response_parser.py -v
```

### Backend API tests (FastAPI + mocked sessions, no network)

These exercise the API layer and endpoint contracts without requiring a live
PostgreSQL instance.

```bash
cd backend
source .venv/bin/activate
pytest tests/test_institutions_api.py tests/test_jobs_api.py tests/test_search_runs_api.py -v
```

### Local integration smoke test (requires PostgreSQL + running backend)

Use this to validate the end-to-end API flow against your local stack.

```bash
cd backend
bash tests/manual_curl_test.sh
```

### Manual tests (requires API key + network)

Use these when you need live Gemini grounding or live verification behavior.

```bash
cd backend
source .venv/bin/activate
python -m tests.manual_search_test "AI safety research labs hiring"
python -m tests.manual_verification_test
```

### Frontend tests

```bash
cd frontend
npm test -- --watchAll=false
```

## Adding a New Verification Check

Add verification checks carefully: they affect storage, audit evidence, and the
frontend evidence matrix.

1. Add the async check function to `backend/app/services/verification_checks.py`.

   ```python
   async def check_new_check(url: str) -> tuple[bool, str]:
       # Return (passed, detail)
       return True, "explanation"
   ```

2. Add the new enum member to `VerificationCheckName` in `backend/app/models/entities.py`.

3. Insert the check into the ordered `CHECKS` list in `backend/app/services/verification_pipeline.py`.
   Keep cheaper checks earlier, because the pipeline is fail-fast and stops on
   the first failure.

4. Create a migration if the persisted enum/schema changed:

   ```bash
   cd backend
   source .venv/bin/activate
   alembic revision --autogenerate -m "add new verification check"
   alembic upgrade head
   ```

5. Update the frontend evidence table order by editing `CHECK_ORDER` in `frontend/src/pages/SearchRunDetail.tsx`.

6. Add or update test coverage in `backend/tests/test_verification_checks.py` and
   `backend/tests/test_verification_pipeline.py`, then run:

   ```bash
   cd backend
   source .venv/bin/activate
   python -m tests.manual_verification_test
   ```

## Database Migrations

Run all Alembic commands from `backend/` with the backend virtual environment
activated.

### Create a new migration

```bash
cd backend
source .venv/bin/activate
alembic revision --autogenerate -m "description of change"
```

Review the generated file in `backend/alembic/versions/` before applying it.

### Apply migrations

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

### Roll back one migration

```bash
cd backend
source .venv/bin/activate
alembic downgrade -1
```

### View current migration state

```bash
cd backend
source .venv/bin/activate
alembic current
```

## Code Style

- Python: run `ruff check backend/`
- TypeScript: run `cd frontend && npx eslint src --ext .ts,.tsx`
- Tests: add or update targeted tests for backend and frontend changes
- Docstrings: prefer Google-style docstrings that explain why a block exists or
  what contract it preserves
- Verification pipeline changes: preserve the cheapest-to-most-expensive check order
- Commits: prefer conventional commit prefixes such as `feat:`, `fix:`, `chore:`, and `docs:`
