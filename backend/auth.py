from datetime import timedelta

from flask import jsonify, request
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)

from models import User

# In-memory user storage. Replaced by SQLAlchemy in U2.
users = {}        # username -> User
email_index = {}  # email -> username


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

        if username in users:
            return jsonify({"error": "Username already exists"}), 409
        if email in email_index:
            return jsonify({"error": "Email already exists"}), 409

        user = User(username=username, email=email, password=password)
        users[username] = user
        email_index[email] = username

        token = create_access_token(identity=username, expires_delta=timedelta(days=7))
        return jsonify({"token": token, "user": _user_payload(user)}), 201

    @app.route('/api/auth/login', methods=['POST'])
    def login():
        data = request.get_json(silent=True) or {}
        identifier = data.get('username') or data.get('email')
        password = data.get('password')

        if not identifier or not password:
            return jsonify({"error": "Username/email and password are required"}), 400

        user = users.get(identifier)
        if user is None:
            mapped = email_index.get(identifier)
            if mapped:
                user = users.get(mapped)

        if user is None or not user.check_password(password):
            return jsonify({"error": "Invalid credentials"}), 401

        token = create_access_token(identity=user.username, expires_delta=timedelta(days=7))
        return jsonify({"token": token, "user": _user_payload(user)})

    @app.route('/api/auth/me', methods=['GET'])
    @jwt_required()
    def me():
        username = get_jwt_identity()
        user = users.get(username)
        if user is None:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"user": _user_payload(user)})

    def get_user(username):
        return users.get(username)

    return get_user


def _user_payload(user):
    return {"id": user.id, "username": user.username, "email": user.email}
