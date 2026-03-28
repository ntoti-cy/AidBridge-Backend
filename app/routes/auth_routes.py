from flask import Blueprint, request, jsonify, current_app
from app.models import Users
from app import db
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import uuid
import jwt
from app.Admin.audit import log_action

auth_bp = Blueprint('auth_bp', __name__)

# REGISTER 
@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    errors = {}

    if not data:
        return jsonify({'error': {'general': ['Invalid Request Body']}}), 400

    # Determine user type based on presence of email
    user_type = 'smartphone' if data.get('email') else 'ussd'


   # Required fields depending on user type
    if user_type == 'smartphone':
        required_fields = ['first_name', 'second_name', 'national_id', 'contact', 'email', 'password']
    else:
        required_fields = ['first_name', 'second_name', 'national_id', 'contact', 'password']

    # Validate required fields
    for field in required_fields:
        if not data.get(field):
            errors.setdefault(field, []).append(f"{field.replace('_', ' ').title()} is required")

    # Additional field-specific validations
    first_name = data.get('first_name')
    if first_name:
        if not first_name.isalpha():
            errors.setdefault('first_name', []).append("First name must contain only letters")

    second_name = data.get('second_name')
    if second_name:
        if not second_name.isalpha():
            errors.setdefault('second_name', []).append("Second name must contain only letters")

    national_id = data.get('national_id')
    if national_id:
        if not national_id.isdigit():
            errors.setdefault('national_id', []).append("National ID must contain only numbers")

    contact = data.get('contact')
    if contact:
        if not contact.isdigit():
            errors.setdefault('contact', []).append("Contact must contain only numbers")
        elif len(contact) < 10:
            errors.setdefault('contact', []).append("Contact must be at least 10 digits long")

    email = data.get('email')
    if user_type == 'smartphone' and email:
        if '@' not in email or '.' not in email:
            errors.setdefault('email', []).append("Email must be a valid email address")
        elif Users.query.filter_by(email=email).first():
            errors.setdefault('email', []).append("Email already exists")

    password = data.get('password')
    if password:
        if len(password) < 6:
            errors.setdefault('password', []).append("Password must be at least 6 characters long")

    # Return all validation errors
    if errors:
        return jsonify({'error': errors}), 400

    # Hash password
    hashed_password = generate_password_hash(password)

    # Create new user
    new_user = Users(
        first_name=first_name,
        second_name=second_name,
        national_id=national_id,
        contact=contact,
        email=email,
        password=hashed_password,
        user_type=user_type,
         role="beneficiary",  
        current_jti=None
    )

    db.session.add(new_user)
    db.session.commit()

#Log the registration in AuditLog
    log_action(new_user.id, "User Registered", f"{new_user.first_name} {new_user.second_name} registered as {new_user.role}")


    return jsonify({
        'message': f'{user_type.capitalize()} user registered successfully',
        'user_id': new_user.id,
        'user_type': new_user.user_type
    }), 201

# ---------------- LOGIN ----------------
@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    errors = {}

    if not data:
        return jsonify({'error': {'general': ['Invalid Request Body']}}), 400

    email = data.get('email')
    contact = data.get('contact')
    password = data.get('password')

    # Password validation
    if not password:
        errors.setdefault('password', []).append("Password is required")
    elif len(password) < 6:
        errors.setdefault('password', []).append("Password must be at least 6 characters long")

    # Email validation
    if email:
        if '@' not in email or '.' not in email:
            errors.setdefault('email', []).append("Email must be a valid email address")

    # Contact validation
    if contact and not contact.isdigit():
        errors.setdefault('contact', []).append("Contact must be a valid number")

    # Return validation errors if any
    if errors:
        return jsonify({'error': errors}), 400

    # SmartPhone login
    user = None
    if email:
        user = Users.query.filter_by(email=email, user_type='smartphone').first()
        if not user or not check_password_hash(user.password, password):
            return jsonify({'error': {'general': ['Invalid email or password']}}), 401

    # USSD login
    elif contact:
        user = Users.query.filter_by(contact=contact, user_type='ussd').first()
        if not user or not check_password_hash(user.password, password):
            return jsonify({'error': {'password': ['Incorrect password']}}), 401
    else:
        return jsonify({'error': {'general': ['Invalid login request']}}), 401

    # Generate session identifier
    jti = str(uuid.uuid4())
    user.current_jti = jti
    db.session.commit()

    #Log the login in AuditLog
    log_action(user.id, "User Logged In", f"{user.first_name} {user.second_name} logged in Successfully")

    # Generate access token
    access_token = jwt.encode({
        'user_id': user.id,
        'role': user.role,
        'jti': jti,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    }, current_app.config['SECRET_KEY'], algorithm="HS256")

    # Generate refresh token
    refresh_token = jwt.encode({
        'user_id': user.id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=10)
    }, current_app.config['SECRET_KEY'], algorithm="HS256")

    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user_type': user.user_type,
        'role': user.role
    })