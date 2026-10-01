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
- **Phase 10 — Concurrency:** version-checked task updates; a stale edit is a 409, never a silent overwrite.
- **Phase 11 — Redis:** realtime events fan out across backend instances via Redis pub/sub.
- **Presence:** live "Online now" per workspace, correct across tabs and instances.

## Database

PostgreSQL and Redis run in Docker:

```bash
docker compose up -d
```

Redis only passes realtime events between backend instances. It stores nothing
(persistence is switched off), and Postgres remains the source of truth.

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
| `PATCH /tasks/{id}` | partial update; any member of the task's workspace; requires `expected_version` |
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

#### Optimistic concurrency

Every `PATCH /tasks/{id}` must include `expected_version`, the version the client
last saw:

```bash
curl -X PATCH localhost:8000/tasks/42 -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"status":"DONE","expected_version":4}'
```

- If the task is still at that version, the update applies, `version` goes up by
  one (4 → 5), and `TASK_UPDATED` is broadcast.
- If the task has moved on, the response is **409** and nothing is written or
  broadcast. The body carries the task as it is now:
  `{"detail": "This task was updated by someone else.", "current_task": {...}}`.

The check is part of the write itself:
`UPDATE tasks ... WHERE id = :id AND version = :expected_version`. A plain
read-compare-write would let two simultaneous requests both pass the comparison,
and the second write would overwrite the first. Postgres instead makes the second
`UPDATE` wait for the first to commit and then re-check its `WHERE`, which no
longer matches, so it becomes a 409. An empty update quoting the current version
is a 200 that changes nothing.

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
`{"type": "connected", "workspace_id", "user_id", "online_users"}`, and it
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
| `USER_JOINED` | a user's first connection to the workspace opens; `{"user": {"id", "email"}}`, not sent to that user |
| `USER_LEFT` | a user's last connection to the workspace closes; `{"user": {"id", ...}}` |

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
them receive events.

#### Presence

`online_users` in the `connected` message is everyone online in the workspace
right now, including you, as `[{"id", "email"}]`. After that, `USER_JOINED` and
`USER_LEFT` keep it current. A user counts once however many tabs, or servers,
they are connected through. `USER_JOINED` fires on their first connection and
`USER_LEFT` only when their last one closes.

Presence is ephemeral and never touches Postgres. With Redis, each workspace has
a sorted set `presence:{id}` holding one member per user per server,
`"{user_id}:{instance_id}"`, scored with an expiry time:

- Someone is online while any of their members is unexpired, so a user on
  server 1 shows as online to a user on server 2.
- Each server refreshes its own members every 10s, and members lapse after 30s.
  If a server dies, its users drop out on their own, and the next sweep by a
  server still serving that workspace sends `USER_LEFT` for them. The sweep uses
  the result of `ZREM` to decide which server sends it, so it goes out once.
- Each add or remove runs in a `MULTI` with a read of what remains, so "first
  connection" and "last connection" are decided atomically.

Each server reconciles the users it has sockets for with the users it has
registered, rather than reacting to individual connects and disconnects. That
way a normal close, a removal from the workspace, a failed send, and a reset
after a Redis outage all end up in the same place. Without Redis, presence is
the local connection manager.

#### Multiple instances (Redis)

Each instance only holds its own sockets. To reach everyone, every event is
published to the Redis channel `workspace:{id}`. Each instance subscribes to
`workspace:*` at startup and delivers what it receives to its local sockets,
including events it published itself. That gives one delivery path, so no
duplicates. If Alice is on server 1 and Bob on server 2, an edit on server 1 goes
Redis → server 2 → Bob. Closing a removed member's sockets travels the same way,
since those sockets may be on another server.

`REDIS_URL` defaults to `redis://localhost:6379/0`. Set it empty (`REDIS_URL=`)
to run one instance with in-memory delivery only.

If Redis goes down, the app falls back to single-instance behaviour instead of
going silent: a publish that fails, or one made while the instance has no
subscription, is delivered to that instance's own sockets directly. The
subscriber reconnects with backoff. Once it is back, it closes its sockets with
`1012` (service restart), because events sent during the gap are lost. Clients
treat that like any dropped connection: they reconnect and re-read from
Postgres.

To try it locally, run two instances on the same Postgres and Redis, and point a
second frontend at the second instance:

```bash
# backend, two terminals
uvicorn app.main:app --port 8000
uvicorn app.main:app --port 8001

# frontend, second terminal
VITE_API_BASE_URL=http://localhost:8001 npx vite --port 5174
```

Log in on http://localhost:5173 and on http://localhost:5174 as two members of
the same workspace. An edit in one window appears in the other, even though they
are connected to different servers. Note that the CORS allow-list in
`app/main.py` only contains `http://localhost:5173`, so add the second origin
while testing.

### Tests

```bash
cd backend
pytest
```

About 180 tests, around 15s, organised by feature:

| File | Covers |
| --- | --- |
| `test_auth.py` | register (duplicates, email and password rules), login (wrong password and unknown email are indistinguishable), and token rejection: missing, expired, wrong signature, `alg: none`, malformed, deleted user |
| `test_authorization.py` | every workspace, task and comment endpoint returns 404 to an outsider, identical to a missing resource; each role can use the workspace; who may add and remove members, grant roles, and remove owners; the last owner rule |
| `test_workspaces.py` | creating, listing and adding members (by email or id), plus the validation and error cases |
| `test_tasks.py` | create, read, update and delete, column ordering, validation, server-owned fields |
| `test_comments.py` | threads, author from the token, validation |
| `test_websockets.py` | connect and reject (4401 / 4404), manager cleanup, events reaching clients, workspace isolation, failed requests broadcasting nothing |
| `test_task_concurrency.py` | optimistic concurrency, including truly simultaneous writers |
| `test_event_bus.py`, `test_presence.py` | Redis fan-out and presence across instances (skipped without Redis) |

Every test leaves the app's connection manager empty; a fixture fails any test
that leaks a socket. bcrypt runs at cost 4 under test, since nothing depends on
the work factor and cost 12 made the suite take minutes.

The tests need the Postgres from `docker compose up -d`. They run against a
separate `<database>_test` database, created on first run, rebuilt each session
and emptied after every test. `tests/conftest.py` points `DATABASE_URL` at it
before anything imports the app. As a backstop, the fixtures refuse to drop or
truncate anything in a database whose name does not end in `_test`. The
concurrency tests rely on real Postgres row locking, so they cannot run on
SQLite.

The app under test runs with Redis switched off. The event-bus tests start two
buses with separate connection managers, standing in for two servers, against
the real Redis, and are skipped if it is not running.

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

Under the header, **Online now** lists everyone with the workspace open, you
first, and the header line shows "*N* users online". Both are seeded on every
(re)connect and updated live. While disconnected they show as unknown rather
than a stale count.

The header shows **Connected / Reconnecting… / Offline**. A dropped connection
retries with jittered exponential backoff (about 1s, 2s, 4s … capped at 30s, six
attempts) and then shows Offline with a Retry button. Losing the network shows
Offline straight away and reconnects as soon as it is back. Events sent while
disconnected are lost, so every reconnect re-reads the task list once. A rejected
token logs you out, and removal from the workspace stops retrying.

Edits carry the version they were based on. That is the version the form was
loaded with, not the live one, so an edit started before someone else's save is
refused rather than quietly overwriting it. While that is the case, the form warns
that saving will be refused. On a 409 the board and the open form switch to the
task as the server returned it, with *"This task was updated by someone else —
showing the latest version."* Nothing is merged, so you redo your edit on top of
the latest version if you still want it. A dragged card cannot be moved again
until its first move has answered, so you never conflict with yourself.

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
