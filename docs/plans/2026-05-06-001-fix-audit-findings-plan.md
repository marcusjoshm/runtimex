---
title: "fix: Address audit findings — bootability, persistence, auth, conflict detection"
type: fix
status: active
date: 2026-05-06
---

# fix: Address audit findings — bootability, persistence, auth, conflict detection

## Overview

The 2026-05-06 initial audit found that runtimex cannot boot, has no persistence, has missing/broken auth on most routes, and ships a stubbed conflict-detection routine that defeats the README's marquee feature. This plan addresses the audit's priorities 1–7 in dependency order: get the app booting, give it durable storage, close the auth gaps, wire the frontend save path, fix the runner timer, build real resource-conflict detection, fire the existing notification plumbing end-to-end, and normalize the API contract.

Frontend tooling modernization (CRA→Vite, MUI v6, TanStack Query — audit priority 8) is intentionally deferred to a follow-up plan; the scope here is correctness and a working development loop, not a tooling rewrite.

---

## Problem Frame

The repo at HEAD ("Complete setup and fix all compilation errors") presents as feature-complete in its README but in practice:

- `backend/auth.py` is truncated mid-function — `register_auth_routes` returns `None`, and `main.py:33` assigns that `None` to `get_user`, so every authed call raises `TypeError`.
- There is no `/api/auth/login` route — the frontend's login form gets a 404.
- `socketio.run(debug=True, ...)` raises `RuntimeError` under Flask-SocketIO 5.5.x without `allow_unsafe_werkzeug=True` or an async worker.
- `run_test()` runs on every boot, polluting the global scheduler with a "Dish 1" demo experiment.
- All state lives in module-level dicts (`auth.py:11`, `scheduler.py:12-13`, `notifications.py:142-143`); a restart wipes users, experiments, and running steps mid-run.
- Most read and step-state-mutation routes have no `@jwt_required` and no ownership check (`main.py:107, 113, 163, 199, 220, 241`).
- `Scheduler.check_for_conflicts` is a stub returning `[]` (`scheduler.py:145-159`).
- The notification service is fully built but never invoked from the real route handlers (the call sites at `main.py:629, 643` are dead module-level functions).
- The `ExperimentDesigner` page only `console.log`s and `alert`s on save (`ExperimentDesigner.tsx:174-178`) — user data is lost.
- The runner's tick interval re-mounts every second due to a state-dependency loop (`ExperimentRunner.tsx:201-231`).
- API URL is hardcoded to `http://localhost:5001` in four files; field-name conventions diverge between camelCase (experiments/steps) and snake_case (notifications).

Goal: ship a fix-pass that turns the current half-built skeleton into a working development foundation, so feature work (templates, sharing polish, watch UX, reporting) can proceed against a stable base.

---

## Requirements Trace

The audit's "Showstopper bugs" and "Significant defects" sections supply the de-facto requirements. R-IDs are this plan's local labels.

- R1. Backend boots cleanly on `python main.py` and serves HTTP 200 on `:5001` without crashing.
- R2. A user can register, log in, receive a JWT, and call protected routes without `TypeError`.
- R3. Restarting the backend preserves users, experiments, steps, templates, and notifications.
- R4. Read and mutation endpoints are gated by `@jwt_required` and enforce ownership/share-permission where applicable.
- R5. The Experiment Designer save button persists to the backend (POST for new, PUT for existing).
- R6. The Experiment Runner's per-second tick does not re-create itself every tick; pause/resume/skip stay in sync with the server.
- R7. The scheduler detects resource conflicts across the planned schedule (not only currently-running steps) and exposes them via API.
- R8. Notifications are emitted by the real route handlers on `step_ready`, `step_completed`, and `resource_conflict`, and the `NotificationCenter` is mounted in the app shell.
- R9. The frontend reads its API base URL from an environment variable; field naming on the wire is consistent (snake_case).
- R10. JWT auth header is restored from `localStorage` before the first authenticated fetch on app load.

---

## Scope Boundaries

- This plan does not migrate CRA → Vite, TS 4 → 5, MUI 5 → 6, or introduce TanStack Query. Those are deferred to a follow-up modernization plan.
- This plan does not introduce a refresh-token flow, password reset, email verification, or OAuth. Login + register + bcrypt + JWT only.
- This plan does not redesign the data model. The existing `Experiment`/`Step`/`User` shapes are preserved and given a persistence layer.
- This plan does not implement multi-experiment cross-scheduling (auto-pushing start times to avoid resource collisions). U6 detects conflicts; rescheduling is a future feature.
- This plan does not add a background timer/tick that auto-completes `FIXED_DURATION` steps. That is captured as deferred follow-up below.
- This plan does not add Alembic / schema migrations. Dev DB is recreated from `models` on first boot; production migration is out of scope until there is a production.
- This plan does not replace `alert()` / `window.prompt()` UX with MUI dialogs. Tracked as deferred polish.

### Deferred to Follow-Up Work

- Frontend tooling modernization (CRA→Vite, TS 5, MUI v6, TanStack Query): separate plan.
- Background tick / auto-completion of `FIXED_DURATION` steps + timeout notifications: separate plan once persistence lands.
- Replace blocking `alert()` / `window.prompt()` with MUI `Snackbar` / `Dialog` flows: tracked as UX polish.
- Schema migrations via Alembic: revisit when a deployment target is chosen.
- Production WSGI/ASGI runner (gunicorn + eventlet/gevent): revisit alongside deployment.

---

## Context & Research

### Relevant Code and Patterns

- `backend/main.py` — Flask app factory + route definitions + global `scheduler`/`notification_service` singletons. All routes live here today.
- `backend/models.py` — `User`, `Experiment`, `Step`, plus `StepStatus`/`StepType` enums. Already uses bcrypt for password hashing (`models.py:130-135`).
- `backend/auth.py` — partial `register` route; intended to expose `register_auth_routes(app, jwt) -> get_user_callable`.
- `backend/scheduler.py` — `Scheduler` class with experiments dict, `calculate_initial_schedule`, `update_ready_status`, and the stubbed `check_for_conflicts`.
- `backend/notifications.py` — fully built `NotificationService` with `add_notification`, factory helpers (`step_ready`, `step_completed`, `resource_conflict`, `user_attention`, `step_timeout`), and SocketIO emit to `user_<username>` rooms.
- `frontend/src/api/client.ts` — axios REST client; CRUD + import/export/share/templates.
- `frontend/src/api/auth.ts` — `register`/`login`/`getCurrentUser`/`logout`; sets `axios.defaults.headers.Authorization` on success.
- `frontend/src/api/socket.ts` and `frontend/src/api/notifications.ts` — two parallel socket.io connections to the same host (consolidate in U8).
- `frontend/src/pages/ExperimentRunner.tsx` — the only page that listens to socket pushes; also the source of the runaway-tick bug.
- `frontend/src/components/NotificationCenter.tsx` — fully implemented but never mounted.

### Institutional Learnings

- None — `docs/solutions/` does not exist yet. The first `ce-compound` writeup for this repo will likely come out of U6 (conflict detection) or U2 (persistence migration).

### External References

- Flask-SocketIO 5.x deployment notes: `socketio.run(..., allow_unsafe_werkzeug=True)` is the documented dev-mode escape hatch when no `eventlet`/`gevent` is installed.
- Flask-JWT-Extended 4.x: `@jwt_required(optional=True)` and `verify_jwt_in_request()` are the two patterns for socket connect handlers.
- SQLAlchemy 2.x declarative + Flask-SQLAlchemy 3.x: the standard Flask persistence pairing; `db.session.add` / `db.session.commit` semantics; `relationship(..., cascade="all, delete-orphan")` for `Experiment.steps`.

---

## Key Technical Decisions

- **Persistence: SQLite + Flask-SQLAlchemy 3.x.** Single-file DB at `backend/runtimex.db`, gitignored. No external service to run; trivial to swap to Postgres later by changing the `SQLALCHEMY_DATABASE_URI`. SQLite is sufficient for lab-scale (single-user or small-team) use during development. Rationale: the cheapest persistence that survives restarts and gives us real `relationship` semantics for experiments→steps and users→experiments.
- **Schema: ORM models live in `backend/models.py` alongside the existing dataclasses.** The dataclasses are kept as a thin to-dict layer the API still serializes; ORM models own write-side state. Avoids a large rename diff while we're also fixing other bugs.
- **No Alembic for now.** Dev DB is created from metadata on first boot. We re-evaluate migrations when there's a deployment target. Tracked as deferred.
- **Wire format: snake_case everywhere.** Notifications already emit snake_case; experiments/steps are the outliers. Backend serializers produce snake_case; frontend TS interfaces are renamed in U8 with a single mechanical pass.
- **Auth: keep Flask-JWT-Extended, add bcrypt via `models.User.set_password`/`verify_password`.** Already half-built — finish it. `JWT_SECRET_KEY` is loaded from env (fallback to a dev default with a startup warning).
- **Socket connect handler uses `verify_jwt_in_request(optional=False, locations=['query_string'])`** to validate tokens before joining the user room. Token-in-query-string is a known leak vector but is what `socket.io` clients ship with by default; addressed in the modernization plan via the `auth` option.
- **Conflict detection: O(n²) interval overlap on `(scheduled_start, scheduled_end, resource_required)` tuples.** Sufficient for the realistic step counts (<200 per experiment, <10 active experiments). Upgrade to an interval tree only if profiling shows it matters.
- **API URL config: `REACT_APP_API_URL` with default `http://localhost:5001`.** Standard CRA pattern; centralized in a new `frontend/src/api/config.ts`.
- **`run_test()` is removed entirely, not gated.** A `tests/` fixture supplies the same demo experiment when needed. Removing it eliminates the global-state pollution risk for good.
- **Frontend stays on CRA for this plan.** A migration is the right call eventually but is its own project; mixing it in here would muddy review.

---

## Open Questions

### Resolved During Planning

- *Should we add Alembic now or later?* Later. No deployment target, no real data, no users; the cost of deferring is zero and it keeps this plan tight.
- *Should we keep two separate socket.io connections (one for experiments, one for notifications)?* No — consolidate to one in U8; the second connection is duplicate work and a second auth surface.
- *Do we need to support both camelCase and snake_case during a transition window?* No — there are no external API consumers yet. Switch the wire format in one PR (U8) and update the TS types in the same diff.

### Deferred to Implementation

- Exact SQLAlchemy column types for `Step` enums (`String` + Python `Enum` adapter vs. SQLAlchemy `Enum` column) — pick during U2 implementation; both work, micro-decision.
- Whether `Step.actual_start_time` becomes `nullable=True` with a default of `NULL` or sentinel epoch-zero — settle when writing the model.
- Where to put the JWT-from-query-string verifier in U1 — inline in the connect handler or as a small helper. Punt to implementer.

---

## Implementation Units

- U1. **Make the backend boot end-to-end**

**Goal:** The app starts cleanly via `python backend/main.py`, register works, login works, an authenticated client can call any endpoint without `TypeError`, and the socket connect handler validates the JWT properly.

**Requirements:** R1, R2, R10 (server side).

**Dependencies:** None.

**Files:**
- Modify: `backend/auth.py` — finish the truncated `register` body; add `/api/auth/login`, `/api/auth/me`; export `get_user(username)` and return it from `register_auth_routes`.
- Modify: `backend/main.py` — pass `allow_unsafe_werkzeug=True` to `socketio.run`; remove `run_test()` and its call site (`main.py:786-789`); replace the bare `verify_jwt_in_request` usage in the socket connect handler with a guarded call inside a `try/except` that disconnects unauthorized sockets; load `JWT_SECRET_KEY` from `os.environ` with a dev fallback + warning log; remove unused imports (`time`, `leave_room`).
- Modify: `backend/requirements.txt` — add `python-dotenv`; remove `Flask-Login` (unused) and unused `pydantic`/`pydantic_core` (kept only if a downstream dep needs them — verify with `pip show`).
- Create: `backend/tests/conftest.py` — pytest fixture that constructs a Flask test client and a fresh `Scheduler`/`NotificationService` per test.
- Create: `backend/tests/test_auth.py`.
- Create: `backend/tests/test_boot.py`.
- Create: `.env.example` — document `JWT_SECRET_KEY`, `FLASK_ENV`, `DATABASE_URL`.

**Approach:**
- `User.set_password(plain)` and `User.verify_password(plain)` already exist in `models.py:130-135` — use them.
- `register` returns `{token, user}` after creating the user, hashing the password, and storing in `users`/`email_index`.
- `login` looks up by `email` (preferred) or `username`, verifies password, returns `{token, user}`. 401 on bad creds.
- `me` decodes JWT, returns `{user}`. Protected with `@jwt_required`.
- `register_auth_routes` returns `lambda username: users.get(username)`; `main.py:33` already assigns it to `get_user`.
- Socket connect: `try: verify_jwt_in_request(locations=['query_string']); identity = get_jwt_identity(); join_room(f"user_{identity}") except: disconnect()`.
- `run_test()` is deleted, not commented out.

**Patterns to follow:**
- Existing `register` body shape (lines 1–32) — mirror it for `login`/`me`.
- `notifications.py` for how `socket_emit` already targets `user_<username>` rooms; the connect handler must populate them.

**Test scenarios:**
- Happy path: `POST /api/auth/register` with fresh creds returns 200 + token; subsequent `GET /api/auth/me` with that token returns the user.
- Happy path: `POST /api/auth/login` with valid creds returns 200 + token.
- Error path: register with duplicate username returns 409; with duplicate email returns 409; with missing field returns 400.
- Error path: login with wrong password returns 401; with unknown username returns 401.
- Error path: `GET /api/auth/me` without token returns 401; with garbage token returns 422.
- Integration: `python -c "import backend.main"` does not raise; the app's `url_map` includes `/api/auth/login` and `/api/auth/me`.
- Integration: `socketio.run(...)` is called with `allow_unsafe_werkzeug=True` (assert via `mock.patch`).

**Verification:**
- `pytest backend/tests/test_auth.py backend/tests/test_boot.py` is green.
- `python backend/main.py &` followed by `curl -s -m 2 http://localhost:5001/api/auth/me` returns 401 (not connection-refused, not 500).
- No demo "Dish 1" experiment is present after a fresh boot.

---

- U2. **Add SQLite persistence (SQLAlchemy ORM)**

**Goal:** Users, experiments, steps, templates, and notifications survive restart. In-memory dicts are removed.

**Requirements:** R3.

**Dependencies:** U1.

**Files:**
- Create: `backend/db.py` — `db = SQLAlchemy()`, `init_db(app)` helper that calls `db.create_all()`.
- Modify: `backend/models.py` — add ORM models `UserORM`, `ExperimentORM`, `StepORM`, `TemplateORM`, `NotificationORM` alongside the existing dataclasses; add `to_dataclass()` / `from_dataclass()` helpers so existing serialization keeps working.
- Modify: `backend/auth.py` — replace `users` / `email_index` dicts with `UserORM` queries; `register`/`login` write/read via `db.session`.
- Modify: `backend/scheduler.py` — `Scheduler.experiments` becomes a query-backed property (or a thin in-memory cache hydrated from DB on init); `add_experiment`/`update_step` persist via `db.session`.
- Modify: `backend/notifications.py` — `NotificationService` reads/writes `NotificationORM`; the in-memory `notifications` and `user_notifications` dicts go away.
- Modify: `backend/main.py` — call `init_db(app)` at startup; configure `SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///runtimex.db')`; remove ad-hoc `scheduler.user_experiments`/`scheduler.templates` attributes (they become ORM queries).
- Modify: `backend/requirements.txt` — add `Flask-SQLAlchemy`, `SQLAlchemy`.
- Modify: `.gitignore` — add `runtimex.db`, `*.db-journal`.
- Create: `backend/tests/test_persistence.py`.

**Approach:**
- ORM tables match dataclass shapes; `Step.dependencies` becomes a self-referential many-to-many via a `step_dependencies` association table.
- `ExperimentORM.steps` uses `relationship(..., cascade="all, delete-orphan", order_by="StepORM.created_at")`.
- `StepStatus` and `StepType` are stored as strings via `Column(String)`; the dataclass layer parses them back to enums.
- `update_experiment` (`main.py:178-195`) is rewritten to *upsert* steps by ID instead of wiping and recreating, fixing the audit's "running steps disappear on PUT" bug.
- For tests, use an in-memory SQLite (`sqlite:///:memory:`) via the conftest fixture.

**Patterns to follow:**
- Standard Flask-SQLAlchemy app-factory pattern: `db = SQLAlchemy()` module-level, `db.init_app(app)` inside `create_app`.
- bcrypt password hash already lives on the dataclass (`models.py:130-135`); mirror onto `UserORM`.

**Test scenarios:**
- Happy path: register a user, restart the app (re-init the test client with a file-based SQLite), log in with the same creds — succeeds.
- Happy path: create an experiment with three steps, restart, fetch — all three steps and their dependencies are intact.
- Edge case: PUT `/api/experiments/<id>` updates names and durations without losing in-flight `RUNNING` step state (this is the regression test for the existing `wipe-and-recreate` bug).
- Edge case: deleting an experiment cascades to its steps and templates derived from it (or blocks if templates exist — pick one and document).
- Integration: a `step.start` SocketIO update is reflected on a fresh client connection because the server hydrates state from DB.
- Integration: `pytest backend/tests/test_persistence.py` runs with `sqlite:///:memory:`.

**Verification:**
- `rm backend/runtimex.db; python backend/main.py` starts; register a user; `kill` the process; restart; log in → succeeds.
- `grep -RnE "^(users|email_index|self\.experiments|self\.user_experiments|self\.templates|self\.notifications|user_notifications) *=" backend/` returns nothing relevant (only ORM-backed accessors remain).

---

- U3. **Auth + ownership enforcement on all routes**

**Goal:** Every read/write endpoint requires a valid JWT and respects ownership/share permissions. Add a minimal `/api/users/search` so the share dialog can resolve usernames.

**Requirements:** R4.

**Dependencies:** U1, U2.

**Files:**
- Modify: `backend/main.py` — add `@jwt_required` to `GET /api/experiments`, `GET /api/experiments/<id>`, `PUT /api/experiments/<id>`, `POST /api/steps/<id>/start|pause|complete`, `GET /api/experiments/<id>/export`, `GET/POST /api/templates`, `DELETE /api/templates/<id>`, `POST /api/experiments/create-from-template/<id>`. Add ownership/share-permission checks before mutation.
- Create: `backend/permissions.py` — small helpers: `can_view_experiment(user, experiment)`, `can_edit_experiment(user, experiment)`, `can_run_step(user, step)`. Returns booleans against the share permission ("view"/"edit") on the experiment.
- Create: `backend/tests/test_permissions.py`.
- Modify: `backend/main.py` — new route `GET /api/users/search?q=<prefix>` returning `[{username, email}]`; `@jwt_required`.

**Approach:**
- A user can view their own experiments + experiments shared with them (any permission). A user can edit only experiments they own or that are shared with `permission == "edit"`. A user can transition step state (start/pause/complete) only on experiments they can edit.
- `GET /api/experiments` becomes "list experiments visible to me" — replaces today's "list all" behavior. The Home page already calls a separate `/api/user/experiments` for the "mine" tab, so this is not a behavior regression.
- `GET /api/experiments/<id>/export` keeps `@jwt_required(optional=True)` semantics only for *publicly shared* experiments; default is required. Document the change.
- `users/search` does prefix matching on `username`, capped at 25 results, returns no email if the user isn't a contact (privacy default).

**Patterns to follow:**
- The existing `share` route (`main.py` ~line 308) already does an ownership check — mirror its pattern.

**Test scenarios:**
- Happy path: owner can `GET`, `PUT`, and `start/pause/complete` their experiment.
- Happy path: a user with `view` share can `GET` but not `PUT`; with `edit` share can do both.
- Error path: an unrelated user gets 404 (not 403 — preserves existence privacy) on `GET /api/experiments/<id>`.
- Error path: missing or expired JWT returns 401 on every previously-unprotected route.
- Edge case: `users/search?q=` (empty) returns 400 or empty list (pick one); `users/search?q=ab` matches only by username prefix.
- Integration: front-end `Home` cold load with a logged-in user calls `/api/experiments` and sees only own + shared.

**Verification:**
- `pytest backend/tests/test_permissions.py` green.
- `grep -RnE "^@app\.route" backend/main.py | grep -v "/api/auth"` and confirm every preceding route has `@jwt_required` on the next line.

---

- U4. **Frontend: protected routes, JWT restore on load, and a working Designer save path**

**Goal:** Authed pages are gated by a `ProtectedRoute` wrapper. The axios `Authorization` header is restored from `localStorage` synchronously on app boot before any fetch fires. The Experiment Designer actually persists.

**Requirements:** R5, R10 (client side).

**Dependencies:** U1, U3.

**Files:**
- Create: `frontend/src/components/ProtectedRoute.tsx` — wrapper that reads token from `localStorage`; renders children if present, redirects to `/login` if not.
- Modify: `frontend/src/api/auth.ts` — export a `bootstrapAuth()` helper that reads `localStorage.getItem('token')` and sets `axios.defaults.headers.common.Authorization` synchronously.
- Modify: `frontend/src/index.tsx` — call `bootstrapAuth()` once before `ReactDOM.render`.
- Modify: `frontend/src/App.tsx` — wrap `/design`, `/run/:id`, `/watch/:id` in `<ProtectedRoute>`.
- Modify: `frontend/src/pages/ExperimentDesigner.tsx` — replace the `console.log` save handler (~line 174) with a real call: `client.createExperiment` for new, `client.updateExperiment` for existing (use `useParams` for the id when editing). On success, navigate to `/`. On error, render an MUI `Alert` (no `alert()`).
- Modify: `frontend/src/pages/ExperimentDesigner.tsx` — fix the `inputProps min:1` bypass at ~line 165 by also validating `currentStep.duration > 0` in the submit handler.
- Modify: `frontend/src/api/client.ts` — fix `exportExperiment` (~line 78) so the download request goes through axios with the auth header (use a Blob download flow), not `window.location.href`.

**Approach:**
- Token restore must happen *synchronously* before render; otherwise the first `getUserExperiments` in `Home.tsx:69-71` races the auth header.
- `ProtectedRoute` only checks token presence; the backend's `@jwt_required` is the real gate. Visual gate only.
- Designer's edit path needs `/design/:id?` route support — add it to `App.tsx`.

**Patterns to follow:**
- Existing axios usage in `frontend/src/api/client.ts` for response shape.
- MUI `Alert` is already used in `Login.tsx` — copy its pattern.

**Test scenarios:**
- Happy path: navigate to `/design` while logged out → redirect to `/login`.
- Happy path: fill the designer with name + 2 steps + dependencies → save → backend has the experiment with both steps; Home shows it.
- Happy path: open `/design/<existing-id>` → load via `client.getExperiment` → modify name → save → PUT lands; running steps preserved (depends on U2).
- Error path: backend returns 422 on a malformed step → `Alert` is rendered with the server error message; no `alert()` modal.
- Edge case: cold reload on `/run/<id>` with a valid token in localStorage → no 401 racing the first render.
- Integration: export-experiment download now sends `Authorization` (network tab inspection or jest with `axios-mock-adapter`).

**Verification:**
- Manual: log in, design an experiment, save, refresh, confirm it's still listed.
- `grep -n "console.log\|alert\|window.prompt" frontend/src/pages/ExperimentDesigner.tsx` returns no results in the save path.

---

- U5. **Fix the runner timer loop, server-sync skip, and step expected-end-time math**

**Goal:** The `ExperimentRunner` per-second tick is stable (does not re-mount each second). Skip is sent to the server, not just to local UI. `Step.get_expected_end_time` accounts for `elapsed_time` for paused/resumed steps.

**Requirements:** R6.

**Dependencies:** U2, U3.

**Files:**
- Modify: `frontend/src/pages/ExperimentRunner.tsx` — replace the experiment-state-dependent `useEffect` interval at lines 201–231 with a `useRef`-based pattern: the interval is created once on mount and reads the latest `experiment` via a ref updated by a separate `useEffect`. Remove `experiment` from the timer effect's dep array. Also fix the dep miss flagged at line 231 (missing `handleStepComplete`).
- Modify: `frontend/src/pages/ExperimentRunner.tsx` — `handleSkip` (~lines 315–345) now POSTs to a new `/api/steps/<id>/skip` endpoint and waits for the socket update instead of mutating local state.
- Modify: `frontend/src/pages/WatchView.tsx` — same skip behavior.
- Modify: `backend/main.py` — add `POST /api/steps/<id>/skip` mirroring the existing `complete` route, with permission checks (U3) and a notification emit (U7 will wire this in).
- Modify: `backend/models.py` — `Step.get_expected_end_time`: when `status == RUNNING`, return `actual_start_time + (duration - elapsed_time)` minus any deduction we already accumulated on pause; when `PAUSED`, return `now + (duration - elapsed_time)`.
- Modify: `backend/models.py` — fix the `Step.start` resume case: if `status == PAUSED`, set `actual_start_time = now` *and* leave `elapsed_time` alone (current code drops original-start info but accumulates correctly; document the shape and add a `first_start_time` field for reporting).
- Modify: `frontend/src/pages/WatchView.tsx` — remove the unused `experiment` binding (audit ESLint warning at line 20).

**Approach:**
- The ref pattern is the standard React fix for "interval reads stale state": one `useRef`, two effects (one writes the ref, one owns the interval), no state in the interval's dep list.
- Server-side skip means the runner state machine has a single source of truth.

**Patterns to follow:**
- `complete` route logic (`main.py` ~line 240) — clone it for `skip` with status set to `SKIPPED`.

**Test scenarios:**
- Happy path: `start` a 1-minute step, watch the elapsed counter advance once per second for 5 seconds (manual Cypress-equivalent or jest with fake timers).
- Happy path: pause at t=10s, resume at t=15s → `elapsed_time == 10s`, `expected_end == now + 50s` (not `now + 60s`, which is today's bug).
- Happy path: skip a step → backend emits `experiment_update` with that step in `SKIPPED`; second client receives the same update.
- Edge case: rapid pause/resume/pause within 1s does not drift `elapsed_time` by more than 1s.
- Integration: with two browser tabs open on the same experiment, clicking skip on tab A reflects on tab B within one socket round-trip.

**Verification:**
- The `useEffect` cleanup function is called exactly once per unmount (assert with a counter ref in dev).
- `pytest backend/tests/test_steps.py::test_skip_route` green.

---

- U6. **Real resource-conflict detection in the scheduler**

**Goal:** `Scheduler.check_for_conflicts` returns a non-empty list when two steps requiring the same resource overlap on the planned schedule. Exposed via `GET /api/experiments/<id>/conflicts` and surfaced in the runner UI.

**Requirements:** R7.

**Dependencies:** U2.

**Files:**
- Modify: `backend/scheduler.py` — replace the stub at `scheduler.py:145-159` with a real implementation: collect all `(step_id, resource_required, scheduled_start_time, scheduled_end_time)` tuples across the experiment, group by `resource_required`, sort by start, walk pairwise to find overlaps. Return `[{step_a, step_b, resource, overlap_seconds}]`.
- Modify: `backend/main.py` — add `GET /api/experiments/<id>/conflicts` (jwt_required + view permission). Return `Scheduler.check_for_conflicts(experiment)`.
- Modify: `backend/main.py` — also call it inside `update_experiment` (U2's rewritten path) and emit a `resource_conflict` notification (U7) for each detected pair on save.
- Modify: `frontend/src/api/client.ts` — add `getConflicts(experimentId)`.
- Modify: `frontend/src/pages/ExperimentRunner.tsx` — fetch conflicts on mount; render a non-blocking MUI `Alert` listing them above the step grid.
- Modify: `frontend/src/pages/ExperimentDesigner.tsx` — same: fetch conflicts after save and surface them.
- Create: `backend/tests/test_conflicts.py`.

**Approach:**
- Definition of "overlap": `a.start < b.end && b.start < a.end` (half-open intervals).
- Resource type "user attention" for `TASK` steps is treated like any other resource (the user is the resource); skip steps with no `resource_required`.
- Multi-experiment cross-checking is **out of scope** — only within a single experiment for v1. Cross-experiment conflicts are a follow-up.

**Patterns to follow:**
- The dataclass shape for `Step.scheduled_start_time` / `scheduled_end_time` (`models.py:53-55`) — reuse those values; don't recompute.

**Test scenarios:**
- Happy path: two `FIXED_DURATION` steps both requiring "microscope", scheduled 14:00–15:00 and 14:30–15:30 → one conflict, `overlap_seconds == 1800`.
- Happy path: two steps requiring different resources at the same time → no conflict.
- Edge case: zero-duration step (sub-minute floor bug from audit) does not crash; skipped from conflict checking with a logged warning.
- Edge case: chained steps with `dependency` constraints that already serialize them produce no spurious conflicts because `scheduled_end <= scheduled_start` of the dependent.
- Edge case: `resource_required` is `None` or empty string → step is skipped.
- Integration: `GET /api/experiments/<id>/conflicts` returns the same list as `Scheduler.check_for_conflicts(...)` directly (round-trip).

**Verification:**
- `pytest backend/tests/test_conflicts.py` green.
- Manual: design two steps that overlap on a resource, save, see the alert in the Runner.

---

- U7. **Wire notifications end-to-end**

**Goal:** The existing `NotificationService` is invoked from the real route handlers on `step_ready`, `step_completed`, and `resource_conflict`, and the `NotificationCenter` is mounted in the app shell so users see them.

**Requirements:** R8.

**Dependencies:** U2, U3, U6.

**Files:**
- Modify: `backend/main.py` — in the real `start`/`pause`/`complete`/`skip` step handlers, after successful state transition, call:
  - `notification_service.add_notification(step_completed_notification(step, experiment, owner_username))`
  - then `update_ready_status` runs; for each newly-`READY` step, emit `step_ready_notification`.
- Modify: `backend/main.py` — delete the dead module-level `handle_step_start`/`handle_step_complete`/`check_resource_conflicts` at `main.py:629-680`; their logic moves into the real handlers (or is already replaced by U6).
- Modify: `frontend/src/components/AppHeader.tsx` — render `<NotificationCenter />` inside the toolbar (or as a `Drawer` toggled by an icon button).
- Modify: `frontend/src/api/notifications.ts` — fix the in-place `is_read`/`is_dismissed` mutation (lines ~175, 191) by replacing the array with a new mapped copy before notifying listeners.
- Create: `backend/tests/test_notifications_wiring.py`.

**Approach:**
- The `add_notification` factory helpers in `notifications.py` (`step_ready_notification`, etc.) already build the right payloads. Just call them.
- `update_ready_status` is the natural hook point — when a step transitions to `READY`, emit one notification per dependent that just became unblocked.

**Patterns to follow:**
- `notifications.py:280-380` factory functions — use as-is.
- `socket_emit` to `user_<username>` rooms is already wired in `NotificationService`; U1 ensures the room is joined.

**Test scenarios:**
- Happy path: completing a step that unblocks a dependent emits exactly one `step_ready` notification per dependent.
- Happy path: saving an experiment with two overlapping resource users emits one `resource_conflict` notification (U6).
- Edge case: completing the last step emits exactly one `step_completed` and zero `step_ready`.
- Edge case: a user who is logged out does not receive notifications (room is empty).
- Integration: a second browser tab logged in as the same user receives the notification within one socket round-trip.
- Mutation regression: `markAsRead(id)` produces a new array reference (assert via `===` inequality in the listener).

**Verification:**
- `pytest backend/tests/test_notifications_wiring.py` green.
- Manual: open Runner in two tabs, complete a step → both tabs show a notification.

---

- U8. **API contract normalization (snake_case) + env config + single socket**

**Goal:** All wire-format field names are snake_case. The frontend reads `REACT_APP_API_URL`. There is one socket.io connection, not two.

**Requirements:** R9.

**Dependencies:** U2, U3, U7.

**Files:**
- Create: `backend/serializers.py` — `experiment_to_dict`, `step_to_dict`, `notification_to_dict`. All output snake_case.
- Modify: `backend/main.py` — replace inline serialization (`main.py:60-90`, `~480-500`) with the new serializers. Fix `// 60` integer-division bug at `main.py:70, 486` by using `total_seconds()` directly (treat duration as seconds end-to-end; UI converts for display).
- Create: `frontend/src/api/config.ts` — `export const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:5001'`.
- Modify: `frontend/src/api/client.ts`, `auth.ts`, `socket.ts`, `notifications.ts` — import `API_URL` from `./config`; remove the four hardcoded URL strings.
- Modify: `frontend/src/api/socket.ts` — pass token via `auth: { token }` instead of `query: { token }`. (Keep the query-string fallback only if the server's connect handler explicitly supports both — U1 chose query-string; align here. Decide one and document.)
- Modify: `frontend/src/api/notifications.ts` — delete the second socket connection; subscribe to `notification` events on the `socket.ts` shared instance instead.
- Modify: `frontend/src/api/client.ts` — rename TS interface fields: `scheduledStartTime` → `scheduled_start_time`, `actualStartTime` → `actual_start_time`, `resourceNeeded` → `resource_required`, `elapsedTime` → `elapsed_time`, `Experiment.sharedWith` → `shared_with`, `createTemplate({experimentId})` → `{experiment_id}`.
- Modify: every `frontend/src/pages/*.tsx` that touches those fields — mechanical rename pass.
- Create: `frontend/.env.example` — document `REACT_APP_API_URL`.

**Approach:**
- snake_case is the lowest-effort end state: backend already half-uses it (notifications), all changes are in TS interface + one mechanical rename.
- Single socket: `socket.ts` is the shared one; `notifications.ts` becomes a thin REST + event-listener module that uses it.

**Patterns to follow:**
- `notifications.ts` interface shape (already snake_case) is the template.

**Test scenarios:**
- Happy path: `JSON.parse(response)` for `GET /api/experiments/<id>` has only snake_case keys (assert via `Object.keys`).
- Happy path: with `REACT_APP_API_URL=http://example.com` in `.env.test`, `client.ts` calls go to that host.
- Edge case: a step with `duration_seconds < 60` round-trips correctly (regression for the `// 60` truncation bug).
- Edge case: two browser tabs open → exactly one socket connection per tab in DevTools (regression for the dual-socket bug).
- Integration: full round-trip — register → create experiment with snake_case payload → fetch → display in Runner — works without any field-name fallbacks.

**Verification:**
- `grep -RnE "scheduledStartTime|actualStartTime|resourceNeeded|elapsedTime|sharedWith|experimentId" frontend/src/` returns no results in production code.
- `grep -RnE "http://localhost:5001" frontend/src/` returns only `frontend/src/api/config.ts`.

---

## System-Wide Impact

- **Interaction graph:** Every authed route now goes through `@jwt_required` → permission helper → DB query → serializer → optional notification emit. A bug in `permissions.py` will cascade to nearly every endpoint; tests (U3) must cover it broadly.
- **Error propagation:** Auth/permission failures must return distinct status codes (401 vs. 403 vs. 404) with consistent JSON shape `{"error": "..."}`. Frontend already reads `err.response.data.error` (audit finding, `Login.tsx:36`); confirm in U1.
- **State lifecycle risks:** U2's wipe-and-recreate fix on `PUT /api/experiments/<id>` is the riskiest correctness change — it preserves running step state across edits. Tests must include "PUT while a step is RUNNING" explicitly.
- **API surface parity:** WatchView consumes the same step shape as the Runner; U8's snake_case rename must touch both. The export JSON format (`exportExperiment`) is also part of the contract surface — keep it snake_case for symmetry; downstream re-imports stay valid.
- **Integration coverage:** Two layers that unit tests alone won't prove — (a) socket connect → JWT → join room → notification delivery (U1 + U7); (b) PUT → conflict re-detection → notification fanout (U2 + U6 + U7). Cover both with integration tests in `test_persistence.py` and `test_notifications_wiring.py`.
- **Unchanged invariants:** The dataclass-shaped payloads used by `import/export` keep their structure (only key naming changes via U8). Templates remain on the same endpoints. `WatchView` URL `/watch/:id` keeps its read-only behavior.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Adding SQLAlchemy mid-flight breaks too many call sites at once. | U2 keeps dataclasses as the serialization layer; ORM models are wired through `to_dataclass()` so the API surface barely moves. Run U2's tests before touching U3+. |
| The `update_experiment` rewrite (preserve running steps on PUT) is the riskiest correctness change. | Dedicated regression test in `test_persistence.py` for "PUT while a step is RUNNING"; manual verification before closing U2. |
| socket.io token-in-query-string is a known leak vector. | Acknowledged; documented in Key Decisions. The modernization plan will switch to the `auth` option once we're ready to coordinate the server-side change. |
| O(n²) conflict detection becomes a hotspot for large experiments. | Punted — current data is well below the threshold where this matters. U6 keeps the function pure so an interval tree replacement is a one-file change. |
| `Flask-Login` and `pydantic` may be transitive deps of something we're keeping. | U1 verifies with `pip show` before removing; if `pydantic` is required by a kept dep (it's a top-level transitive), leave it. |
| CRA's deprecated webpack-dev-server middleware warnings will keep showing up. | Accepted; the tooling rewrite is a separate plan. |
| Two truncated `auth.py` lines suggest the working tree was lost — there may be more incomplete files we haven't found. | U1 includes a `python -c "import backend.main"` smoke test as the first verification step; any other truncation surfaces immediately. |

---

## Documentation / Operational Notes

- README's "Getting Started" section needs a one-line update for `.env.example` and the new login/register flow (deferred, low-priority — the README is currently mostly accurate from a user POV).
- After this plan lands, capture institutional learnings in `docs/solutions/` for: (a) the wipe-and-recreate-on-PUT pattern that lost step state, (b) the `setInterval` + state dep loop, (c) the snake_case wire format decision.
- `start.sh` should `cp .env.example .env` if `.env` is missing; defer to U1 only if trivial.

---

## Sources & References

- **Origin document:** None — the audit chat output of 2026-05-06 is the de-facto origin.
- Audit findings location: this conversation's "runtimex — Initial Audit (2026-05-06)" message.
- Relevant code: `backend/main.py`, `backend/auth.py`, `backend/scheduler.py`, `backend/models.py`, `backend/notifications.py`, `frontend/src/pages/ExperimentRunner.tsx`, `frontend/src/pages/ExperimentDesigner.tsx`, `frontend/src/api/*.ts`.
- External docs:
  - Flask-SocketIO 5.x deployment notes (allow_unsafe_werkzeug)
  - Flask-JWT-Extended 4.x docs (verify_jwt_in_request, get_jwt_identity)
  - Flask-SQLAlchemy 3.x docs (init_app, db.create_all, relationship cascade)
