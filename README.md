# CollabSpace

A real-time collaborative workspace. Built in phases.

- **Phase 1 — Project setup:** FastAPI backend and Vite/React frontend running independently, frontend calling `GET /health`.
- **Phase 2 — Database:** PostgreSQL, SQLAlchemy models, Alembic migrations. No API routes, no auth yet.
- **Phase 3 — Authentication:** register, login, and a JWT-protected `/auth/me`.
- **Phase 4 — Workspaces:** create/list/read workspaces and manage membership. No task routes yet.

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

`backend/.env` needs a `JWT_SECRET_KEY`. There is deliberately no default, so the
app refuses to start without one rather than signing tokens with a value that is
public knowledge:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Authentication

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/register` | email + password → 201 with the new user (409 if taken) |
| `POST /auth/login` | email + password → `access_token` (401 on bad credentials) |
| `GET /auth/me` | requires `Authorization: Bearer <token>` → the current user |

```bash
curl -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-good-password"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-good-password"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

### Workspaces

Every route below requires `Authorization: Bearer <token>`.

| Endpoint | Who can call it |
| --- | --- |
| `POST /workspaces` | any signed-in user; the creator becomes `OWNER` |
| `GET /workspaces` | returns only the caller's own workspaces |
| `GET /workspaces/{id}` | members only |
| `POST /workspaces/{id}/members` | owner or admin |
| `DELETE /workspaces/{id}/members/{user_id}` | owner or admin |

Add a member by `user_id` or by `email` (exactly one):

```bash
curl -X POST localhost:8000/workspaces/1/members \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"email":"teammate@example.com","role":"MEMBER"}'
```

Role rules:

- Owners and admins can add and remove members.
- Only an owner can grant `ADMIN` or `OWNER`, and only an owner can remove another owner.
- The last owner cannot be removed, so a workspace is never left unadministered.

A workspace the caller is not a member of returns **404, not 403** — a 403 would
confirm that it exists. A non-existent workspace and someone else's workspace are
indistinguishable from the outside.

Passwords are hashed with bcrypt and never stored or returned in plaintext.
Tokens are HS256, expire after `ACCESS_TOKEN_EXPIRE_MINUTES`, and carry only the
user id in `sub`. There is no refresh token or logout yet — a token is valid
until it expires.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on http://localhost:5173 and calls the backend's `/health` on load.
The API base URL comes from `VITE_API_BASE_URL` in `frontend/.env`.
