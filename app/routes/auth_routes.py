from xml.parsers.expat import errors

from flask import Blueprint, request, jsonify, current_app
from app.models import Household, TokenBlocklist, Users
from app import db
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import uuid
import jwt
from app.Admin.audit import log_action
from app.tokens import token_required

auth_bp = Blueprint("auth_bp", __name__)


# REGISTER
@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    errors = {}

    if not data:
        return jsonify({"error": {"general": ["Invalid Request Body"]}}), 400

    for key, value in data.items():
        if isinstance(value, str):
            data[key] = value.strip()

    user_type = "smartphone" if data.get("email") else "ussd"

    if user_type == "smartphone":
        required_fields = [
            "first_name",
            "second_name",
            "national_id",
            "contact",
            "email",
            "password",
        ]
    else:
        required_fields = [
            "first_name",
            "second_name",
            "national_id",
            "contact",
            "password",
        ]

    for field in required_fields:
        value = data.get(field)
        
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.setdefault(field, []).append(
                f"{field.replace('_', ' ').title()} is required and cannot be empty"
            )

    first_name = data.get("first_name")
    if first_name and not first_name.isalpha():
        errors.setdefault("first_name", []).append(
            "First name must contain only letters"
        )

    second_name = data.get("second_name")
    if second_name and not second_name.isalpha():
        errors.setdefault("second_name", []).append(
            "Second name must contain only letters"
        )

    national_id = data.get("national_id")
    if national_id and not str(national_id).isdigit():
        errors.setdefault("national_id", []).append(
            "National ID must contain only numbers"
        )

    contact = data.get("contact")
    if contact:
        contact_str = str(contact).replace("+", "")
        if not contact_str.isdigit():
            errors.setdefault("contact", []).append("Contact must contain only numbers")
        elif len(contact_str) < 10:
            errors.setdefault("contact", []).append(
                "Contact must be at least 10 digits long"
            )
        else:
            data["contact"] = contact_str
            contact = contact_str

    email = data.get("email")
    if user_type == "smartphone" and email:
        if email is None or (isinstance(email, str) and not email.strip()):
            errors.setdefault("email", []).append("Email is required and cannot be empty")
        elif "@" not in email or "." not in email:
            errors.setdefault("email", []).append("Email must be a valid email address")
        elif Users.query.filter_by(email=email).first():
            errors.setdefault("email", []).append("Email already exists")

    password = data.get("password")
    if password and len(password) < 6:
        errors.setdefault("password", []).append(
            "Password must be at least 6 characters long"
        )

    if errors:
        return jsonify({"error": errors}), 400
    
    existing_contact = Users.query.filter_by(contact=contact).first()
    if existing_contact:
        errors.setdefault("contact", []).append(
            "A User with this phone number already exists"
        )
    
    existing_national_id = Users.query.filter_by(national_id=national_id).first()
    if existing_national_id:
        errors.setdefault("national_id", []).append(
            "A User with this National ID already exists"
        )
    
    if errors:
        return jsonify({"errors": errors}), 400

    hashed_password = generate_password_hash(password)

    new_user = Users(
        first_name=first_name,
        second_name=second_name,
        national_id=national_id,
        contact=contact,
        email=email,
        password=hashed_password,
        user_type=user_type,
        role="beneficiary",
        current_jti=None,
    )

    db.session.add(new_user)
    db.session.commit()

    log_action(
        new_user.id,
        "User Registered",
        f"{new_user.first_name} {new_user.second_name} registered as {new_user.role}",
    )

    return (
        jsonify(
            {
                "message": f"{user_type.capitalize()} user registered successfully",
                "user_id": new_user.id,
                "user_type": new_user.user_type,
            }
        ),
        201,
    )


# LOGIN
@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    errors = {}

    if not data:
        return jsonify({"error": {"general": ["Invalid Request Body"]}}), 400

    for key, value in data.items():
        if isinstance(value, str):
            data[key] = value.strip()

    email = data.get("email")
    contact = data.get("contact")
    password = data.get("password")

    # Validate password not empty
    if password is None or (isinstance(password, str) and not password.strip()):
        errors.setdefault("password", []).append("Password is required and cannot be empty")
    elif len(password) < 6:
        errors.setdefault("password", []).append(
            "Password must be at least 6 characters long"
        )

    if email is None or (isinstance(email, str) and not email.strip()):
        errors.setdefault("email", []).append(
            "Email is required"
        )
    elif "@" not in email or "." not in email:
        errors.setdefault("email", []).append(
            "Email must be a valid email address"
        )
    

    is_contact_empty = contact is None or (isinstance(contact, str) and not contact.strip())

   
    if not is_contact_empty:
            if not str(contact).isdigit():
                errors.setdefault("contact", []).append("Contact must be a valid number")

    if errors:
        return jsonify({"error": errors}), 400
    
    if contact and not is_contact_empty:
        user = Users.query.filter_by(contact=contact).first()

    if not user or not check_password_hash(user.password, password):
        return jsonify({"error": {"general": ["Invalid credentials"]}}), 401

    user_role = user.role
    user_type = user.user_type
    # must_change_password = user.requires_password_change

    session_jti = str(uuid.uuid4())
    user.current_jti = session_jti
    db.session.commit()

    log_action(
        user.id,
        "User Logged In",
        f"{user.first_name} {user.second_name} logged in Successfully",
    )

    access_token = jwt.encode(
        {
            "user_id": user.id,
            "role": user_role,
            "jti": session_jti,
            "type": "access",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1),
        },
        current_app.config["SECRET_KEY"],
        algorithm="HS256",
    )

    refresh_token = jwt.encode(
        {
            "user_id": user.id,
            "role": user_role,
            "jti": session_jti,
            "type": "refresh",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=10),
        },
        current_app.config["SECRET_KEY"],
        algorithm="HS256",
    )

    household = Household.query.filter_by(user_id=user.id).first()
    is_profile_complete = False
    if household:
        is_profile_complete = household.is_profile_complete

    return jsonify(
        {
            "message": "Login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "requires_password_change": (
                user.requires_password_change if user.role == "aid_worker" else False
            ),
            "user_type": user_type,
            "role": user_role,
            "is_profile_complete": is_profile_complete,
        }
    )

# LOGOUT
@auth_bp.route("/logout", methods=["POST"])
@token_required
def logout(current_user_id):
    auth_token = request.headers.get("Authorization").split(" ")[1]
    decoded_token = jwt.decode(
        auth_token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
    )
    session_jti = decoded_token.get("jti")

    revoked_token = TokenBlocklist(jti=session_jti, user_id=current_user_id)
    db.session.add(revoked_token)

    # Query only Users table
    user = Users.query.get(current_user_id)

    if user:
        user.current_jti = None

    db.session.commit()
    return jsonify({"message": "Successfully logged out. Tokens revoked."}), 200


# REFRESH TOKEN
@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    auth_header = request.headers.get("Authorization")
    if not auth_header or " " not in auth_header:
        return jsonify({"error": "Refresh token is missing"}), 401

    token = auth_header.split(" ")[1]

    try:
        data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        if data.get("type") != "refresh":
            return (
                jsonify({"error": "Invalid token type. Must be a refresh token."}),
                401,
            )

        user_id = data.get("user_id")
        session_jti = data.get("jti")
        user_role = data.get("role")

        if TokenBlocklist.query.filter_by(jti=session_jti).first():
            return (
                jsonify({"error": "Session has been revoked. Please log in again."}),
                401,
            )

        # Query only Users table
        user = Users.query.get(user_id)

        if not user:
            return jsonify({"error": "User not found."}), 404

        if user.current_jti != session_jti:
            return (
                jsonify(
                    {
                        "error": "Session invalid. You may have logged in on another device."
                    }
                ),
                401,
            )

        new_access_token = jwt.encode(
            {
                "user_id": user.id,
                "role": user_role,
                "jti": session_jti,
                "type": "access",
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1),
            },
            current_app.config["SECRET_KEY"],
            algorithm="HS256",
        )

        new_refresh_token = jwt.encode(
            {
                "user_id": user.id,
                "role": user_role,
                "jti": session_jti,
                "type": "refresh",
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=10),
            },
            current_app.config["SECRET_KEY"],
            algorithm="HS256",
        )

        return (
            jsonify(
                {
                    "message": "Token refreshed successfully",
                    "access_token": new_access_token,
                    "refresh_token": new_refresh_token,
                }
            ),
            200,
        )

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Refresh token expired. Please log in again."}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid refresh token."}), 401
