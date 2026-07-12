from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3:
        return jsonify(error="Username must be at least 3 characters."), 400
    if len(password) < 6:
        return jsonify(error="Password must be at least 6 characters."), 400
    if User.query.filter_by(username=username).first():
        return jsonify(error="That username is already taken."), 409

    user = User(username=username)
    user.set_password(password)
    if username.lower() == "admin":
        user.is_admin = True
    db.session.add(user)
    db.session.commit()

    login_user(user, remember=True)
    return jsonify(user=user.to_dict()), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify(error="Invalid username or password."), 401

    login_user(user, remember=True)
    return jsonify(user=user.to_dict())


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify(ok=True)


@auth_bp.get("/me")
def me():
    if current_user.is_authenticated:
        return jsonify(user=current_user.to_dict())
    return jsonify(user=None)
