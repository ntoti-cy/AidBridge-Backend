from flask import Blueprint, jsonify, request
from app.Admin.audit import log_action
from app.models import  AidTokens, DistributionCenter, Users
from app import db
from datetime import datetime
from app.tokens import generate_aid_token, token_required


officer_bp = Blueprint('officer_bp', __name__)


@officer_bp.route('/start-distribution-session', methods=['POST'])
@token_required
def start_distribution_session(current_user_id):
    # verify the officer is assigned to a center
    worker = Users.query.get(current_user_id)
    if not worker.assigned_center_id:
        return jsonify({"error": "You must be assigned to a distribution center ."}), 403
    center = DistributionCenter.query.get(worker.assigned_center_id)

    center.is_active = True
    center.start_time = datetime.utcnow()

    expiry_time_str = request.json.get("expiry_time")
    if expiry_time_str:
        center.expiry_time = datetime.strptime(expiry_time_str, "%Y-%m-%d %H:%M:%S")

    db.session.commit()

    log_action(
        current_user_id,
        "Distribution Session Started",
        f"Officer {worker.first_name} {worker.second_name} started distribution session at center {center.aid_center_name}"
    )

    return jsonify({
        "message": f"Distribution session started for {center.aid_center_name}",
        "center_id": center.id
    }), 200



@officer_bp.route('/end-distribution-session/<int:session_id>', methods=['POST'])
@token_required
def end_distribution_session(current_user_id, session_id):
    worker = Users.query.get(current_user_id)
    center = DistributionCenter.query.get(worker.assigned_center_id)

    if not center:
        return jsonify({"error": "Center Session not found"}), 404

    AidTokens.query.filter_by(
        distribution_center_id=center.id).update({"token_status": "expired"})


    center.is_active = False  
    db.session.commit()

    log_action(
        current_user_id,
        "Distribution Session Ended",
        f"Officer {worker.first_name} {worker.second_name} ended distribution session at center {center.aid_center_name}"
    )
    return jsonify({"message": f"Distribution session for {center.aid_center_name} ended"}), 200

@officer_bp.route('/verify-token', methods=['POST'])
@token_required
def verify_token(current_user_id):

    # manual token OR QR value
    token_value = request.json.get("aid_token")

    if not token_value:
        return jsonify({"error": "Token required"}), 400

    # Find token
    token = AidTokens.query.filter_by(aid_token=token_value).first()

    if not token:
        return jsonify({"error": "Invalid token"}), 404

    session = DistributionCenter.query.get(token.distribution_center_id)

    #Ensure token belongs to the session
    if not token.distribution_center_id == session.id:
        return jsonify({"error": "Token not associated with an active session"}), 400

    # Check session exists and active
    if not session or not session.is_active:
        token.token_status = "expired"
        db.session.commit()
        return jsonify({"error": "Distribution session inactive"}), 400

    # Automatic expiry check
    if session.expiry_time and session.expiry_time < datetime.utcnow():
        token.token_status = "expired"
        db.session.commit()
        return jsonify({"error": "Token expired"}), 400

    if token.token_status == "used":
        return jsonify({"error": "Token already used"}), 400

    if token.token_status == "expired":
        return jsonify({"error": "Token expired"}), 400

    # Mark as used
    token.token_status = "used"
    db.session.commit()

    return jsonify({
        "message": "Token verified successfully",
        "beneficiary_id": token.user_id,
        "distribution_center": session.aid_center_name
    }), 200



@officer_bp.route('/download-beneficiaries', methods=['GET'])
@token_required
def download_beneficiaries(current_user_id):
    # Find the currently active distribution session
    active_session = DistributionCenter.query.filter_by(is_active=True).first()

    if not active_session:
        return jsonify({"error": "No active distribution session found."}), 404

    # Get ONLY the tokens that belong to this specific active session
    session_tokens = AidTokens.query.filter_by(distribution_center_id=active_session.id).all()

    data = []

    # Loop through the tokens and fetch the matching User details
    for token in session_tokens:
        user = Users.query.get(token.user_id) 
        
        if user:
            data.append({
                "national_id": user.national_id,
                "name": f"{user.first_name} {user.second_name}",
                "aid_token": token.aid_token, 
                "token_status": token.token_status
            })

    return jsonify({
        "message": "Data downloaded successfully",
        "session_name": active_session.aid_center_name,
        "beneficiaries": data
    }), 200