from flask import Blueprint, current_app, request, jsonify
import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import DistributionCenter, Household, Users  # Removed Officers
from app import db
from app.tokens import token_required

crud_bp = Blueprint('crud_bp', __name__)

@crud_bp.route('/change-password', methods=['POST'])
@token_required
def change_password(current_user_id):
    data = request.get_json()
    old_password = data.get('old_password')
    new_password = data.get('new_password')

    if not new_password or len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters long'}), 400


    user = Users.query.get(current_user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404


    
    is_forced_change = (
        user.role == "aid-worker" and user.requires_password_change
    )

    if not is_forced_change:
        if not old_password:
            return jsonify({'error': 'Old password is required to change your password.'}), 400
        
        if not check_password_hash(user.password, old_password):
            return jsonify({'error': 'Incorrect old password.'}), 401

    if check_password_hash(user.password, new_password):
        return jsonify({'error': 'New password cannot be the same as the current password.'}), 400

    user.password = generate_password_hash(new_password)

    if user.role == "aid-worker" :
        user.requires_password_change = False

    db.session.commit()

    return jsonify({
        'message': 'Password updated successfully.',
        'role': user.role
    }), 200

# User Profile 
@crud_bp.route('/me', methods=['GET'])
@token_required
def get_my_profile(current_user_id):
   
    user = Users.query.get(current_user_id)

    if not user:
        return jsonify({'error': 'User profile not found'}), 404

    return jsonify({
        'first_name': user.first_name,
        'second_name': user.second_name,
        'national_id': user.national_id,
        'contact': user.contact,
        'email': user.email,
        'role': user.role,
        'requires_password_change': user.requires_password_change
    }), 200



@crud_bp.route('/complete-profile', methods=['POST'])
@token_required
def complete_profile(current_user_id):

    user = Users.query.get(current_user_id)
    if user.role != 'beneficiary':
        return jsonify({"error": "Unauthorized: Only beneficiaries complete profiles"}), 403
    
    data = request.get_json()
    
    # Check if household exists or create one
    household = Household.query.filter_by(user_id=current_user_id).first()
    if not household:
        household = Household(user_id=current_user_id)
        db.session.add(household)

    # Update fields
    household.total_members = data.get('total_members', household.total_members)
    household.dependents_count = data.get('dependents_count', household.dependents_count)
    household.disability_present = data.get('disability_present', household.disability_present)
    household.center_id = data.get('center_id',household.center_id)
    
    # Calculate score and set status
    household.vulnerability_score = household.calculate_score()
    household.is_profile_complete = True
    
    db.session.commit()
    return jsonify({"message": "Profile setup complete", "score": household.vulnerability_score}), 200



@crud_bp.route('/get-centers', methods=['GET'])
def get_centers():
    # Fetch active centers 
    centers = DistributionCenter.query.filter_by(is_active=True).all()
    return jsonify([{"id": c.id, "name": c.aid_center_name} for c in centers]), 200