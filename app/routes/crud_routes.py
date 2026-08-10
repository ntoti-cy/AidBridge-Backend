import datetime
import re

from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import DistributionCenter, Household, Users
from app import db
from app.tokens import token_required
from app.utilis.sessions import auto_expire_session

crud_bp = Blueprint("crud_bp", __name__)


@crud_bp.route("/change-password", methods=["POST"])
@token_required
def change_password(current_user_id):
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    old_password = data.get("old_password")
    new_password = data.get("new_password")

    if not new_password or len(new_password) < 6:
        return (
            jsonify({"error": "New password must be at least 6 characters long"}),
            400,
        )

    user = Users.query.get(current_user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    is_forced_change = user.role == "aid_worker" and user.requires_password_change

    if not is_forced_change:
        if not old_password:
            return (
                jsonify({"error": "Old password is required to change your password."}),
                400,
            )

        if not check_password_hash(user.password, old_password):
            return jsonify({"error": "Incorrect old password."}), 401

    if check_password_hash(user.password, new_password):
        return (
            jsonify(
                {"error": "New password cannot be the same as the current password."}
            ),
            400,
        )

    user.password = generate_password_hash(new_password)

    if user.role == "aid_worker":
        user.requires_password_change = False

    db.session.commit()

    return (
        jsonify({"message": "Password updated successfully.", "role": user.role}),
        200,
    )


# Forgot Password
@crud_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    email = data.get("email")
    national_id = data.get("national_id")

    if email:
        email = email.strip().lower()

    if national_id:
        national_id = national_id.strip()

    identifier = email or national_id
    new_password = data.get("new_password")

    if not identifier or not new_password:
        return (
            jsonify({"error": "Email/National ID and new password are required."}),
            400,
        )

    if len(new_password) < 6:
        return (
            jsonify({"error": "New password must be at least 6 characters long"}),
            400,
        )

    # Find user by email or national ID
    user = Users.query.filter(
        (Users.email == identifier) | (Users.national_id == identifier)
    ).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if check_password_hash(user.password, new_password):
        return (
            jsonify(
                {"error": "New password cannot be the same as the current password."}
            ),
            400,
        )

    # Update password and clear forced change flag if it exists
    user.password = generate_password_hash(new_password)
    if hasattr(user, "requires_password_change") and user.requires_password_change:
        user.requires_password_change = False

    db.session.commit()

    return jsonify({"message": "Password reset successfully."}), 200


# User Profile
@crud_bp.route("/me", methods=["GET"])
@token_required
def get_my_profile(current_user_id):
    user = Users.query.get(current_user_id)
    if not user:
        return jsonify({"error": "User profile not found"}), 404

    household = Household.query.filter_by(user_id=user.id).first()

    center = None
    assigned_center_id = None

    # 1. Check if the user is an officer with a direct center assignment
    if hasattr(user, "assigned_center_id") and user.assigned_center_id:
        assigned_center_id = user.assigned_center_id
        center = DistributionCenter.query.get(assigned_center_id)

    # 2. Fallback to household center assignment if not found (for beneficiaries)
    elif household and household.center_id:
        assigned_center_id = household.center_id
        center = DistributionCenter.query.get(household.center_id)


    if center:
        auto_expire_session(center)
             

    is_profile_complete = False
    total_members = None
    dependents_count = None
    income_level = None
    disability_present = None
    vulnerability_score = None
    if household:
        is_profile_complete = household.is_profile_complete
        total_members = household.total_members
        dependents_count = household.dependents_count
        income_level = household.income_level
        disability_present = household.disability_present
        vulnerability_score = household.vulnerability_score

  
    center_is_active = False    
    center_expiry_time = None
    if center:
        center_is_active = center.is_active

    if center and center.expiry_time:
        center_expiry_time = center.expiry_time.isoformat()

    return (
        jsonify(
            {
                "first_name": user.first_name,
                "second_name": user.second_name,
                "national_id": user.national_id,
                "contact": user.contact,
                "email": user.email,
                "role": user.role,
                "is_profile_complete": is_profile_complete,
                "requires_password_change": user.requires_password_change,
                "assigned_center_id": assigned_center_id,
                "assigned_center_name": center.aid_center_name if center else None,
                "center_is_active": center_is_active,
                "center_expiry_time": center_expiry_time,
                "total_members": total_members,
                "dependents_count": dependents_count,
                "income_level": income_level,
                "disability_present": disability_present,
                "vulnerability_score": vulnerability_score,
            }
        ),
        200,
    )


@crud_bp.route("/update-profile", methods=["PUT"])
@token_required
def update_profile(current_user_id):
    user = Users.query.get(current_user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    # Fields both Beneficiary and Field Officer can edit
    if "first_name" in data:
        user.first_name = data["first_name"].strip()
    if "second_name" in data:
        user.second_name = data["second_name"].strip()
    if "national_id" in data:
        user.national_id = str(data["national_id"]).strip()
    if "contact" in data:
        user.contact = str(data["contact"]).strip()

    # BENEFICIARY SPECIFIC UPDATES
    if user.role == "beneficiary":
        # Beneficiaries can update email if provided
        if "email" in data:
            user.email = data["email"].strip()

        household = Household.query.filter_by(user_id=current_user_id).first()
        if not household:
            household = Household(user_id=current_user_id)
            db.session.add(household)

        if "total_members" in data:
            val = int(data["total_members"])
            if val < 1:
                return jsonify({"error": "Total members must be at least 1."}), 400
            household.total_members = val

        if "dependents_count" in data:
            val = int(data["dependents_count"])
            if val < 0:
                return jsonify({"error": "Dependents cannot be negative."}), 400
            household.dependents_count = val

        if "disability_present" in data:
            household.disability_present = bool(data["disability_present"])

        if "income_level" in data:
            raw_income = data["income_level"]
            if isinstance(raw_income, (int, float)):
                household.income_level = float(raw_income)
            elif isinstance(raw_income, str):
                cleaned_income = re.sub(r"[^\d.]", "", raw_income)
                household.income_level = float(cleaned_income) if cleaned_income else 0.0

        if "center_id" in data:
            household.center_id = data["center_id"]
            user.assigned_center_id = data["center_id"]

        # Recalculate vulnerability score on household update
        household.calculate_score()
        household.is_profile_complete = True

    # Save changes
    try:
        db.session.commit()
        return jsonify({"message": "Profile updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to update profile: {str(e)}"}), 500


@crud_bp.route("/complete-profile", methods=["POST"])
@token_required
def complete_profile(current_user_id):

    user = Users.query.get(current_user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    if user.role != "beneficiary":
        return (
            jsonify({"error": "Unauthorized: Only beneficiaries complete profiles"}),
            403,
        )

    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    # Check if household exists or create one
    household = Household.query.filter_by(user_id=current_user_id).first()
    if not household:
        household = Household(user_id=current_user_id)
        db.session.add(household)

    # Update fields
    household.total_members = data.get("total_members", household.total_members)
    household.dependents_count = data.get(
        "dependents_count", household.dependents_count
    )
    household.disability_present = data.get(
        "disability_present", household.disability_present
    )
    if "income_level" in data:
        raw_income = data.get("income_level")
        if isinstance(raw_income, (int, float)):
            household.income_level = float(raw_income)
        elif isinstance(raw_income, str):
            cleaned_income = re.sub(r"[^\d.]", "", raw_income)
            household.income_level = float(cleaned_income) if cleaned_income else 0.0
        else:
            household.income_level = 0.0

    center_id = data.get("center_id")
    if center_id:
        household.center_id = center_id
        user.assigned_center_id = center_id

    if household.total_members < 1:
        return jsonify({"error": "Total members must be at least 1."}), 400

    if household.dependents_count < 0:
        return jsonify({"error": "Dependents cannot be negative."}), 400

    # Calculate score and set status
    household.calculate_score()
    household.is_profile_complete = True

    db.session.commit()
    return (
        jsonify(
            {
                "message": "Profile setup complete",
                "score": household.vulnerability_score,
            }
        ),
        200,
    )


# Fetch all distribution centers
@crud_bp.route("/get-centers", methods=["GET"])
def get_centers():
    centers = DistributionCenter.query.all()

    return (
        jsonify(
            [
                {
                    "id": c.id,
                    "name": c.aid_center_name,
                    "is_active": getattr(c, "is_active", True),
                }
                for c in centers
            ]
        ),
        200,
    )
