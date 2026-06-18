from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app.models import DistributionCenter, Household, Household, Users
from app import db
from werkzeug.security import generate_password_hash
from app.Admin.audit import log_action
from app.Admin.decorators import admin_required

admin_bp = Blueprint('admin_bp', __name__)

@admin_bp.route('/create-aid-worker', methods=['POST'])
@admin_required
def create_aid_worker(current_user):
    data = request.get_json()
    errors = {}

    if not data:
        return jsonify({'error': {'general': ['Invalid Request Body']}}), 400

    # Required fields (same style as register)
    required_fields = ['first_name', 'second_name', 'national_id', 'contact', 'email', 'password']

    for field in required_fields:
        if not data.get(field):
            errors.setdefault(field, []).append(f"{field.replace('_', ' ').title()} is required")

    # Extract fields
    first_name = data.get('first_name')
    second_name = data.get('second_name')
    national_id = data.get('national_id')
    contact = data.get('contact')
    email = data.get('email')
    password = data.get('password')

    # Field validations (MATCH REGISTER STYLE)
    if first_name and not first_name.isalpha():
        errors.setdefault('first_name', []).append("First name must contain only letters")

    if second_name and not second_name.isalpha():
        errors.setdefault('second_name', []).append("Second name must contain only letters")

    if national_id:
        if not str(national_id).isdigit():
            errors.setdefault('national_id', []).append("National ID must contain only numbers")
        elif Users.query.filter_by(national_id=national_id).first():
            errors.setdefault('national_id', []).append("National ID already exists")

    if contact:
        if not contact.isdigit():
            errors.setdefault('contact', []).append("Contact must contain only numbers")
        elif len(contact) < 10:
            errors.setdefault('contact', []).append("Contact must be at least 10 digits long")
        elif Users.query.filter_by(contact=contact).first():
            errors.setdefault('contact', []).append("Contact already exists")

    if email:
        if '@' not in email or '.' not in email:
            errors.setdefault('email', []).append("Email must be a valid email address")
        elif Users.query.filter_by(email=email).first():
            errors.setdefault('email', []).append("Email already exists")

    if password:
        if len(password) < 6:
            errors.setdefault('password', []).append("Password must be at least 6 characters long")

    if errors:
        return jsonify({'error': errors}), 400

    hashed_password = generate_password_hash(password)

    
    new_worker = Users(
        first_name=first_name,
        second_name=second_name,
        national_id=national_id,
        contact=contact,
        email=email,
        password=hashed_password,
        user_type='smartphone',
        role='aid_worker',
        requires_password_change=True,
        current_jti=None
    )

    db.session.add(new_worker)
    db.session.commit()

    # Audit log 
    log_action(
    current_user.id,
    "Aid Worker Created",
    f"{new_worker.first_name} {new_worker.second_name} created as Aid Worker"
)

    return jsonify({
        'message': f'Aid Worker {first_name} {second_name} created successfully',
        'user_id': new_worker.id,
        'role': new_worker.role
    }), 201



@admin_bp.route('/assign-worker-to-center', methods=['POST'])
@admin_required
def assign_worker(current_user):
    data = request.get_json()
    worker_id = data.get('worker_id')
    center_id = data.get('center_id')
    
    worker = Users.query.get(worker_id)
    center = DistributionCenter.query.get(center_id)
    
    if not worker or not center:
        return jsonify({"error": "Worker or Center not found"}), 404
    
    
    worker.assigned_center_id = center.id
    db.session.commit()
    
    
    log_action(
        current_user.id, 
        "Worker Assigned to Center", 
        f"Admin {current_user.first_name} assigned worker {worker.first_name} {worker.second_name} to center {center.aid_center_name}"
    )
    
    return jsonify({
        "message": f"Worker {worker.first_name} assigned to {center.aid_center_name} successfully"
    }), 200

@admin_bp.route('/analytics/summary', methods=['GET'])
@admin_required
def get_analytics(current_user):
    # Coverage Distribution
    coverage_data = db.session.query(
        DistributionCenter.aid_center_name, 
        func.count(Household.id)
    ).join(Household, DistributionCenter.id == Household.center_id, isouter=True)\
     .group_by(DistributionCenter.aid_center_name).all()

    # 2. Vulnerability Distribution
    tiers_data = db.session.query(
        func.case(
            (Household.vulnerability_score > 10, 'High'),
            (Household.vulnerability_score >= 5, 'Medium'),
            else_='Low'
        ).label('tier'),
        func.count(Household.id)
    ).group_by('tier').all()

    return jsonify({
        "coverage": [{"center": c[0], "count": c[1]} for c in coverage_data],
        "vulnerability_tiers": [{"tier": t[0], "count": t[1]} for t in tiers_data]
    }), 200