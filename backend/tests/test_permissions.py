"""Permission + auth-enforcement tests for U3.

Covers:
- Owner can read / edit / transition step state on their own experiments.
- View-share grants GET but blocks PUT and step transitions (403).
- Edit-share grants both GET and PUT.
- Unrelated users get 404 (existence privacy) on a foreign experiment.
- Missing-JWT spot checks on every previously-unprotected route -> 401.
- /api/users/search prefix-matching (case-insensitive), empty-q rejection,
  and email non-leakage.
"""
from tests.conftest import register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_experiment(client, headers, name="ExpA", with_steps=True):
    """Create an experiment owned by the user behind ``headers``. Returns dict."""
    payload = {
        "name": name,
        "description": "test",
        "steps": [],
    }
    if with_steps:
        payload["steps"] = [
            {"name": "S1", "duration": 5, "type": "task", "dependencies": []},
            {"name": "S2", "duration": 7, "type": "task", "dependencies": []},
        ]
    r = client.post("/api/experiments", headers=headers, json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _share(client, owner_headers, experiment_id, target_username, permission):
    r = client.post(
        f"/api/experiments/{experiment_id}/share",
        headers=owner_headers,
        json={"username": target_username, "permission": permission},
    )
    assert r.status_code == 200, r.get_json()


def _force_step_ready(step_id):
    """Bypass the scheduler READY-check so start/pause/complete are deterministic."""
    import main as main_module
    from models import StepStatus

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.status = StepStatus.READY


# ---------------------------------------------------------------------------
# 1. Owner happy paths
# ---------------------------------------------------------------------------
def test_owner_can_get_put_and_run_step(client, auth_headers):
    exp = _create_experiment(client, auth_headers, "OwnerExp")
    exp_id = exp["id"]
    step_id = exp["steps"][0]["id"]

    # GET
    r = client.get(f"/api/experiments/{exp_id}", headers=auth_headers)
    assert r.status_code == 200

    # PUT
    r = client.put(
        f"/api/experiments/{exp_id}",
        headers=auth_headers,
        json={
            "name": "OwnerExp Renamed",
            "description": "edited",
            "steps": [
                {"id": step_id, "name": "S1 Renamed", "duration": 5, "type": "task"},
                {"id": exp["steps"][1]["id"], "name": "S2", "duration": 7, "type": "task"},
            ],
        },
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["name"] == "OwnerExp Renamed"

    # Step transitions (start -> pause -> complete).
    _force_step_ready(step_id)
    r = client.post(f"/api/steps/{step_id}/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    r = client.post(f"/api/steps/{step_id}/pause", headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    r = client.post(f"/api/steps/{step_id}/complete", headers=auth_headers)
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# 2. View-share: GET allowed, PUT blocked
# ---------------------------------------------------------------------------
def test_view_share_allows_get_blocks_put(client, auth_headers, second_user_headers):
    exp = _create_experiment(client, auth_headers, "ShareViewExp")
    exp_id = exp["id"]

    _share(client, auth_headers, exp_id, "bob", "view")

    # Bob can GET.
    r = client.get(f"/api/experiments/{exp_id}", headers=second_user_headers)
    assert r.status_code == 200

    # Bob cannot PUT.
    r = client.put(
        f"/api/experiments/{exp_id}",
        headers=second_user_headers,
        json={"name": "Hijacked", "steps": []},
    )
    assert r.status_code == 403
    assert r.get_json()["error"] == "edit permission required"


# ---------------------------------------------------------------------------
# 3. Edit-share: GET and PUT allowed
# ---------------------------------------------------------------------------
def test_edit_share_allows_get_and_put(client, auth_headers, second_user_headers):
    exp = _create_experiment(client, auth_headers, "ShareEditExp")
    exp_id = exp["id"]

    _share(client, auth_headers, exp_id, "bob", "edit")

    r = client.get(f"/api/experiments/{exp_id}", headers=second_user_headers)
    assert r.status_code == 200

    r = client.put(
        f"/api/experiments/{exp_id}",
        headers=second_user_headers,
        json={
            "name": "Edited By Bob",
            "description": "bob was here",
            "steps": [
                {"id": s["id"], "name": s["name"], "duration": 5, "type": "task"}
                for s in exp["steps"]
            ],
        },
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["name"] == "Edited By Bob"


# ---------------------------------------------------------------------------
# 4. Unrelated user gets 404 (existence privacy)
# ---------------------------------------------------------------------------
def test_unrelated_user_gets_404_on_foreign_experiment(client, auth_headers, second_user_headers):
    exp = _create_experiment(client, auth_headers, "PrivateExp")
    exp_id = exp["id"]

    # Bob has no relationship to PrivateExp -- should look like it doesn't exist.
    r = client.get(f"/api/experiments/{exp_id}", headers=second_user_headers)
    assert r.status_code == 404


def test_list_experiments_filters_to_visible_only(client, auth_headers, second_user_headers):
    """GET /api/experiments returns only own + shared experiments."""
    _create_experiment(client, auth_headers, "AliceExp1")
    bob_exp = _create_experiment(client, second_user_headers, "BobExp1")

    # Alice sees only her own experiment, not Bob's.
    r = client.get("/api/experiments", headers=auth_headers)
    assert r.status_code == 200
    names = {e["name"] for e in r.get_json()}
    assert "AliceExp1" in names
    assert "BobExp1" not in names

    # Once Bob shares, Alice sees it.
    _share(client, second_user_headers, bob_exp["id"], "alice", "view")
    r = client.get("/api/experiments", headers=auth_headers)
    visible_names = {e["name"] for e in r.get_json()}
    assert "BobExp1" in visible_names


# ---------------------------------------------------------------------------
# 5. Missing-JWT spot checks -> 401
# ---------------------------------------------------------------------------
def test_missing_jwt_returns_401_on_protected_routes(client, auth_headers):
    """Spot-check the previously-unprotected routes return 401 without a token."""
    exp = _create_experiment(client, auth_headers, "AuthCheckExp")
    exp_id = exp["id"]
    step_id = exp["steps"][0]["id"]

    # GET /api/experiments
    assert client.get("/api/experiments").status_code == 401
    # GET /api/experiments/<id>
    assert client.get(f"/api/experiments/{exp_id}").status_code == 401
    # PUT /api/experiments/<id>
    assert client.put(f"/api/experiments/{exp_id}", json={"name": "x"}).status_code == 401
    # POST /api/steps/<id>/start
    assert client.post(f"/api/steps/{step_id}/start").status_code == 401
    # POST /api/steps/<id>/pause
    assert client.post(f"/api/steps/{step_id}/pause").status_code == 401
    # POST /api/steps/<id>/complete
    assert client.post(f"/api/steps/{step_id}/complete").status_code == 401
    # GET /api/templates
    assert client.get("/api/templates").status_code == 401
    # GET /api/experiments/<id>/export
    assert client.get(f"/api/experiments/{exp_id}/export").status_code == 401
    # GET /api/users/search
    assert client.get("/api/users/search?q=al").status_code == 401


# ---------------------------------------------------------------------------
# 6+7+8. /api/users/search behavior
# ---------------------------------------------------------------------------
def test_users_search_empty_q_returns_400(client, auth_headers):
    r = client.get("/api/users/search?q=", headers=auth_headers)
    assert r.status_code == 400
    assert r.get_json()["error"] == "q parameter required"


def test_users_search_prefix_match_case_insensitive(client, auth_headers):
    # auth_headers registers `alice`. Add an `Albert` and a `Beatrice` so we
    # can check that prefix=al matches al-prefix only and ignores case.
    register_user(client, "Albert", "albert@example.com")
    register_user(client, "Beatrice", "beatrice@example.com")

    r = client.get("/api/users/search?q=al", headers=auth_headers)
    assert r.status_code == 200
    usernames = sorted(u["username"] for u in r.get_json())
    # SQLite stores usernames as-given but ilike is case-insensitive.
    assert "alice" in usernames
    assert "Albert" in usernames
    assert "Beatrice" not in usernames

    # Same prefix uppercase -- still matches.
    r = client.get("/api/users/search?q=AL", headers=auth_headers)
    usernames_upper = sorted(u["username"] for u in r.get_json())
    assert set(usernames) == set(usernames_upper)


def test_users_search_does_not_leak_email(client, auth_headers):
    register_user(client, "carol", "carol@example.com")
    r = client.get("/api/users/search?q=ca", headers=auth_headers)
    assert r.status_code == 200
    payload = r.get_json()
    assert payload, "expected at least one match"
    for entry in payload:
        assert "email" not in entry
        assert set(entry.keys()) == {"username"}


# ---------------------------------------------------------------------------
# 9. Step transitions: viewer cannot start/pause/complete
# ---------------------------------------------------------------------------
def test_view_share_cannot_run_step_transitions(client, auth_headers, second_user_headers):
    exp = _create_experiment(client, auth_headers, "ViewShareStepExp")
    exp_id = exp["id"]
    step_id = exp["steps"][0]["id"]

    _share(client, auth_headers, exp_id, "bob", "view")
    _force_step_ready(step_id)

    # Bob (view-only) cannot start.
    r = client.post(f"/api/steps/{step_id}/start", headers=second_user_headers)
    assert r.status_code == 403
    assert r.get_json()["error"] == "edit permission required"

    # Owner starts so we have something to pause/complete.
    r = client.post(f"/api/steps/{step_id}/start", headers=auth_headers)
    assert r.status_code == 200

    # Bob cannot pause.
    r = client.post(f"/api/steps/{step_id}/pause", headers=second_user_headers)
    assert r.status_code == 403

    # Bob cannot complete.
    r = client.post(f"/api/steps/{step_id}/complete", headers=second_user_headers)
    assert r.status_code == 403


def test_unrelated_user_gets_404_on_step_transition(client, auth_headers, second_user_headers):
    """Step routes inherit experiment existence-privacy: 404 when the user
    can't see the parent experiment, NOT 403, so step IDs aren't enumerable."""
    exp = _create_experiment(client, auth_headers, "PrivateStepExp")
    step_id = exp["steps"][0]["id"]
    _force_step_ready(step_id)

    r = client.post(f"/api/steps/{step_id}/start", headers=second_user_headers)
    assert r.status_code == 404
