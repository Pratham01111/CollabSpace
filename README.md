# CollabSpace

A real-time collaborative workspace. Built in phases.

- **Phase 1 — Project setup:** FastAPI backend and Vite/React frontend running independently, frontend calling `GET /health`.
- **Phase 2 — Database:** PostgreSQL, SQLAlchemy models, Alembic migrations. No API routes, no auth yet.

## Database

PostgreSQL runs in Docker:

```bash
docker compose up -d db
```

Connection string lives in `backend/.env` (see `backend/.env.example`):

```
DATABASE_URL=postgresql+psycopg://collabspace:collabspace@localhost:5432/collabspace
```

### Migrations

Run from `backend/` with the virtualenv active:

```bash
alembic upgrade head          # apply migrations
alembic downgrade base        # roll everything back
alembic revision --autogenerate -m "describe change"   # after editing models
alembic current               # what's applied
alembic history               # revision log
```

Always read a generated migration before applying it — autogenerate is a first draft, not a finished one.

### Schema

| Table | Notes |
| --- | --- |
| `users` | unique index on `email` |
| `workspaces` | |
| `workspace_members` | association object; unique on `(workspace_id, user_id)`, carries `role` |
| `tasks` | `status` enum, float `position` for ordering, `version` for optimistic concurrency |
| `comments` | indexed on `(task_id, created_at)` for threaded reads |

Deleting a workspace cascades to its members and tasks; deleting a task cascades to its comments.
Deleting a user cascades to their memberships and comments, but their tasks survive with
`created_by` set to `NULL`.

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- `GET /health` → `{"status": "ok"}`
- Docs at http://localhost:8000/docs

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on http://localhost:5173 and calls the backend's `/health` on load.
The API base URL comes from `VITE_API_BASE_URL` in `frontend/.env`.
