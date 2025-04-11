from flask import jsonify, request
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity
)
import datetime
from models import User

# In-memory user storage (in a real app, this would be a database)
users = {}  # username -> User object
email_index = {}  # email -> username

def register_auth_routes(app, jwt):
    @app.route('/api/auth/register', methods=['POST'])
    def register():
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        # Validate input
        if not username or not email or not password:
            return jsonify({"error": "Username, email, and password are required"}), 400
        
        # Check if username or email already exists
        if username in users:
            return jsonify({"error": "Username already exists"}), 409
        if email in email_index:
            return jsonify({"error": "Email already exists"}), 409
        
        # Create new user
        user 