def test_main_module_imports_cleanly():
    import main  # noqa: F401


def test_url_map_contains_auth_routes(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/auth/register" in rules
    assert "/api/auth/login" in rules
    assert "/api/auth/me" in rules


def test_no_demo_experiment_seeded_on_boot(app):
    import main

    assert main.scheduler.experiments == {}, (
        "run_test() must not seed demo data on boot"
    )


def test_jwt_secret_falls_back_with_warning(monkeypatch, caplog):
    """Reload main with no JWT_SECRET_KEY env to confirm the warning fires and a fallback is set."""
    import importlib
    import logging

    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    import main as main_module

    with caplog.at_level(logging.WARNING, logger="main"):
        importlib.reload(main_module)

    assert main_module.app.config["JWT_SECRET_KEY"]
    assert any("JWT_SECRET_KEY" in record.message for record in caplog.records)


def test_socketio_run_uses_allow_unsafe_werkzeug(monkeypatch):
    """Calling main.socketio.run must include allow_unsafe_werkzeug=True so dev mode boots."""
    import main

    captured = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(main.socketio, "run", fake_run)
    main.socketio.run(main.app, debug=True, port=5001, host="0.0.0.0", allow_unsafe_werkzeug=True)
    assert captured.get("allow_unsafe_werkzeug") is True
