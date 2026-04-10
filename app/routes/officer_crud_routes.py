from flask import Blueprint, jsonify, request
from app.Admin.audit import log_action
from app.models import  AidTokens, DistributionSession, Users
from app import db
from datetime import datetime
from app.tokens import generate_aid_token, token_required


officer_bp = Blueprint('officer_bp', __name__)


@officer_bp.route('/start-distribution-session', methods=['POST'])
@token_required
def start_distribution_session(current_user_id):
    # Logic to start a distribution session
    
    aid_center_name = request.json.get('aid_center_name')
    expiry_time_str= request.json.get('expiry_time') 
    
    if not aid_center_name or not expiry_time_str:
        return "Missing required fields", 400
    
    session= DistributionSession(
        aid_center_name=aid_center_name,
        expiry_time=datetime.strptime(expiry_time_str, '%Y-%m-%d %H:%M:%S'),
        is_active=True

        
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        "message": "Distribution session started", 
        "session_id": session.id}), 200
   
@officer_bp.route('/end-distribution-session/<int:session_id>', methods=['POST'])
@token_required
def end_distribution_session(current_user_id, session_id):
    session = DistributionSession.query.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    #Expires all unused active aid tokens
    AidTokens.query.filter_by(
        distribution_session_id=session_id,
        token_status='active'
        ).update({"token_status": "expired"})
    
    session.is_active = False
    db.session.commit()

    return jsonify({"message": "Distribution session ended"}), 200

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

    session = DistributionSession.query.get(token.distribution_session_id)

    #Ensure token belongs to the session
    if not token.distribution_session_id == session.id:
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
    active_session = DistributionSession.query.filter_by(is_active=True).first()

    if not active_session:
        return jsonify({"error": "No active distribution session found."}), 404

    # Get ONLY the tokens that belong to this specific active session
    session_tokens = AidTokens.query.filter_by(distribution_session_id=active_session.id).all()

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