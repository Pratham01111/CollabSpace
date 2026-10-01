# CollabSpace

A real-time collaborative workspace. Built in phases.

- **Phase 1 — Project setup:** FastAPI backend and Vite/React frontend running independently, frontend calling `GET /health`.
- **Phase 2 — Database:** PostgreSQL, SQLAlchemy models, Alembic migrations. No API routes, no auth yet.
- **Phase 3 — Authentication:** register, login, and a JWT-protected `/auth/me`.
- **Phase 4 — Workspaces:** create/list/read workspaces and manage membership.
- **Phase 5 — Tasks:** board CRUD scoped to a workspace.
- **Phase 6 — Frontend:** login, workspace dashboard, and a Kanban board. No WebSockets yet.
- **Phase 7 — WebSockets:** an authenticated per-workspace connection, tracked server-side.
- **Phase 8 — Real-time sync:** task create/update/delete pushed to every open board, with reconnection.
- **Phase 9 — Comments:** persisted task comments, delivered live.

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
| `DELETE /workspaces/{id}/members/me` | any member, to leave |

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
- Any member can leave via `.../members/me`, whatever their role. The last-owner
  rule still applies: promote someone else to owner first, or the request is a 409.

A workspace the caller is not a member of returns **404, not 403** — a 403 would
confirm that it exists. A non-existent workspace and someone else's workspace are
indistinguishable from the outside.

### Tasks

| Endpoint | Notes |
| --- | --- |
| `GET /workspaces/{id}/tasks` | members only; ordered by status then position |
| `POST /workspaces/{id}/tasks` | members only; `created_by` comes from the token |
| `PATCH /tasks/{id}` | partial update; any member of the task's workspace |
| `DELETE /tasks/{id}` | any member of the task's workspace |

Statuses are `TODO`, `IN_PROGRESS`, `DONE`. A task in a workspace the caller does
not belong to returns 404, exactly as the workspace routes do.

`position` orders cards within one status column, and columns are numbered
independently. Omit it on create and the card is appended to the bottom of its
column; change `status` without sending a `position` and the card lands at the
bottom of the column it moved into. It is a float so that dropping a card between
two others is a single write at the midpoint rather than a renumber of everything
below it.

`created_by`, `version`, `workspace_id` and the timestamps are server-owned.
Sending any of them in a request body is a 422 rather than a silent no-op, so a
client bug surfaces immediately.

`version` increments on every update that changes something. Nothing checks it
yet — the 409-on-stale-write comparison arrives in Phase 10.

Passwords are hashed with bcrypt and never stored or returned in plaintext.
Tokens are HS256, expire after `ACCESS_TOKEN_EXPIRE_MINUTES`, and carry only the
user id in `sub`. There is no refresh token or logout yet — a token is valid
until it expires.

### Comments

| Endpoint | Notes |
| --- | --- |
| `GET /tasks/{id}/comments` | the thread, oldest first |
| `POST /tasks/{id}/comments` | `{"body": "..."}` → 201 with the comment |

```json
{ "id": 7, "task_id": 42, "author": { "id": 3, "email": "bob@example.com" }, "body": "Looks good", "created_at": "..." }
```

The author always comes from the token, and sending `author` in the body is a
422. The body is trimmed and must be 1 to 5000 characters. Access is the same
check the task routes use: a task you cannot see is a 404 for its comments too.
Comments are deleted along with their task.

### WebSockets

`WS /ws/workspaces/{id}?token=<access_token>` opens a live channel to one workspace.
The token goes in the query string because browsers cannot set headers on a
WebSocket. It is checked exactly as the REST routes check it, and the caller must
be a member of the workspace.

A rejected connection is accepted and then closed immediately, so the client
receives a close code and reason (a refusal during the handshake arrives as a bare
HTTP 403):

| Close code | Meaning |
| --- | --- |
| `4401` | missing, invalid or expired token, or the user no longer exists |
| `4404` | no such workspace, or not a member (deliberately the same, as over REST); also sent to a member's open sockets when they leave or are removed |

On success the server sends
`{"type": "connected", "workspace_id", "user_id", "connected_user_ids"}`, and it
answers a text `ping` with `{"type": "pong"}`.

#### Events

Every successful task write is broadcast to everyone connected to that task's
workspace, including the person who made it:

```json
{ "type": "TASK_UPDATED", "task": { "id": 42, "title": "Build API", "status": "DONE", "version": 3, ... } }
```

| Type | Sent after |
| --- | --- |
| `TASK_CREATED` | `POST /workspaces/{id}/tasks` |
| `TASK_UPDATED` | `PATCH /tasks/{id}` (not for an empty body, which changes nothing) |
| `TASK_DELETED` | `DELETE /tasks/{id}`; `task` is the task as it was just before deletion |
| `COMMENT_CREATED` | `POST /tasks/{id}/comments`; carries `comment` instead of `task` |

`task` is exactly what the REST endpoint returns. Events are queued as background
tasks only once the service call, which commits, has returned, and FastAPI runs
background tasks only when the handler succeeds. A request that fails validation,
permission checks or the commit therefore never produces an event, so clients
never see state that is not in the database.

```bash
# websocat, or any WebSocket client
websocat "ws://localhost:8000/ws/workspaces/1?token=$TOKEN"
```

A user may have several sockets open on one workspace (say, two tabs), and all of
them receive events. Connections are held in process memory, so this works only
with a single worker.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on http://localhost:5173. The API base URL comes from `VITE_API_BASE_URL`
in `frontend/.env`.

### Screens

| Route | What it does |
| --- | --- |
| `/login` | log in or create an account; redirects to the dashboard on success |
| `/workspaces` | "My Workspaces" list + create |
| `/workspaces/:id` | Kanban board: TODO / IN PROGRESS / DONE |

The dashboard and board are behind a route guard, so a logged-out visitor is sent
to `/login` and returned to wherever they were headed after signing in. The token
lives in `localStorage`; a 401 from any request other than a login attempt clears
it and drops you back to the login page.

Cards show the title and "Created by <name>". The API stores `created_by` as a
user id, so the name is resolved client-side from the member list that
`GET /workspaces/{id}` already returns — no extra endpoint needed.

Drag a card between columns, or change its status in the detail view; either way
it is a `PATCH /tasks/{id}`. The detail view also edits the title and
description, and deletes the task behind a confirm step.

The board stays live over the workspace WebSocket. Other people's changes appear
without a reload: events are applied to local state, never by refetching. A task
can arrive twice, once in the REST response to your own change and once in its
broadcast, so cards are de-duplicated by id and an update never replaces a newer
`version` with an older one. If someone else edits the task you have open, your
unsaved edits are kept.

The header shows **Connected / Reconnecting… / Offline**. A dropped connection
retries with jittered exponential backoff (about 1s, 2s, 4s … capped at 30s, six
attempts) and then shows Offline with a Retry button. Losing the network shows
Offline straight away and reconnects as soon as it is back. Events sent while
disconnected are lost, so every reconnect re-reads the task list once. A rejected
token logs you out, and removal from the workspace stops retrying.

Opening a task loads its comment thread, and posting goes through the API. A
`COMMENT_CREATED` for the open task is appended live; one for another task is
picked up when that task is opened. The open thread is re-read on reconnect, like
the board. If a post fails, the text stays in the box with the error beneath it.

### Guest mode (temporary)

The login page offers **Continue as guest**, which provisions a throwaway account
through the real API and seeds it with a demo workspace and four tasks, so the UI
can be looked at without signing up.

It is a development convenience, not a shared demo login:

- Each browser gets its own randomly generated account, so there is no fixed
  credential for anyone who finds the deployment, and one guest cannot see
  another's board.
- The data is real — it is written to Postgres like any other account's.
- It is enabled automatically in `npm run dev`. A production build has to opt in
  with `VITE_ENABLE_GUEST=true`.
- Credentials are kept in `localStorage`, so returning as a guest resumes the
  same sandbox. Clear site data to start fresh.

Remove the button by dropping the `isGuestEnabled()` block in
`src/pages/Login.jsx` when it is no longer wanted.
