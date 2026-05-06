from datetime import timedelta

from flask import jsonify, request
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)

from db import db
from models import User, UserORM


def register_auth_routes(app, jwt):
    """Register /api/auth/* routes and return a get_user(username) helper."""

    @app.route('/api/auth/register', methods=['POST'])
    def register():
        data = request.get_json(silent=True) or {}
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if not username or not email or not password:
            return jsonify({"error": "Username, email, and password are required"}), 400

        if UserORM.query.filter_by(username=username).first():
            return jsonify({"error": "Username already exists"}), 409
        if UserORM.query.filter_by(email=email).first():
            return jsonify({"error": "Email already exists"}), 409

        user = User(username=username, email=email, password=password)
        db.session.add(UserORM.from_dataclass(user))
        db.session.commit()

        token = create_access_token(identity=username, expires_delta=timedelta(days=7))
        return jsonify({"token": token, "user": _user_payload(user)}), 201

    @app.route('/api/auth/login', methods=['POST'])
    def login():
        data = request.get_json(silent=True) or {}
        identifier = data.get('username') or data.get('email')
        password = data.get('password')

        if not identifier or not password:
            return jsonify({"error": "Username/email and password are required"}), 400

        user_orm = (
            UserORM.query.filter_by(username=identifier).first()
            or UserORM.query.filter_by(email=identifier).first()
        )

        if user_orm is None:
            return jsonify({"error": "Invalid credentials"}), 401

        user = user_orm.to_dataclass()
        if not user.check_password(password):
            return jsonify({"error": "Invalid credentials"}), 401

        token = create_access_token(identity=user.username, expires_delta=timedelta(days=7))
        return jsonify({"token": token, "user": _user_payload(user)})

    @app.route('/api/auth/me', methods=['GET'])
    @jwt_required()
    def me():
        username = get_jwt_identity()
        user_orm = UserORM.query.filter_by(username=username).first()
        if user_orm is None:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"user": _user_payload(user_orm.to_dataclass())})

    def get_user(username):
        """Return a User dataclass for ``username`` or None.

        Kept for compatibility with `main.py` route handlers that still expect
        a dataclass-shaped object with ``shared_experiments``, ``check_password``,
        etc. Callers that need to MUTATE shared_experiments must go through
        ``persist_user`` (or query UserORM directly) so changes hit the DB.
        """
        orm = UserORM.query.filter_by(username=username).first()
        return orm.to_dataclass() if orm else None

    return get_user


def persist_user(user: User) -> None:
    """Write a dataclass User's mutable fields back to the DB.

    Used by share/permission flows in main.py that mutate ``user.shared_experiments``.
    """
    orm = UserORM.query.filter_by(username=user.username).first()
    if orm is None:
        return
    orm.apply_dataclass(user)
    db.session.commit()


def _user_payload(user):
    return {"id": user.id, "username": user.username, "email": user.email}
