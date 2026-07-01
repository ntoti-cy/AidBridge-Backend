import token

from flask import Blueprint, jsonify, request
from app.Admin.audit import log_action
from app.models import  AidTokens, AuditLog, DistributionCenter, Household, Users
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
        distribution_center_id=center.id, token_status="active").update({"token_status": "expired"})


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

    token_value = request.json.get("aid_token")
    if not token_value:
       return jsonify({"error": "Token required"}), 400

    token = AidTokens.query.filter_by(aid_token=token_value).first()
    if not token:
        return jsonify({"error": "Invalid token"}), 404
    
    officer = Users.query.get(current_user_id)
    if token.distribution_center_id != officer.assigned_center_id:
        return jsonify({
        "error": "This token belongs to another distribution center."
    }), 403


    session = DistributionCenter.query.get(token.distribution_center_id)
    if not session or not session.is_active:
        return jsonify({"error": "Distribution session inactive or not found"}), 400

    # Automatic expiry check
    if session.expiry_time and session.expiry_time < datetime.utcnow():
        token.token_status = "expired"
        db.session.commit()
        return jsonify({"error": "Token expired"}), 400

    if token.token_status in ["used", "expired"]:
        return jsonify({"error": f"Token status is {token.token_status}"}), 400

    # Correctly query the user and household
    user = Users.query.get(token.user_id)
    household = Household.query.filter_by(user_id=token.user_id).first()

    if not user:
        return jsonify({"error": "Beneficiary not found"}), 404


    log_action(
    current_user_id,
    "Token Verified",
    f"Verified token {token.aid_token} for beneficiary {user.id}"
)

    return jsonify({
        "message": "Token verified successfully",
        "beneficiary": {
            "id": user.id,
            "name": f"{user.first_name} {user.second_name}",
            "national_id": user.national_id,
            "total_members": household.total_members if household else 0,
            "dependents_count": household.dependents_count if household else 0,
            "income_level": household.income_level if household else 0,
            "disability_present": household.disability_present if household else False,
            "distribution_center": session.aid_center_name,
            "aid_token": token.aid_token,
            "token_status": token.token_status,
            "aid_collected":  token.token_status == "used"
        }
    }), 200


@officer_bp.route('/collect-aid', methods=['POST'])
@token_required
def collect_aid(current_user_id):

    token_value = request.json.get("aid_token")
    if not token_value:
        return jsonify({"error": "Token required"}), 400
    
    officer = Users.query.get(current_user_id)
    token = AidTokens.query.filter_by(
            aid_token=token_value
        ).first()

    if not token:
        return jsonify({"error": "Invalid token"}), 404
        
    if token.distribution_center_id != officer.assigned_center_id:
           return jsonify({
            "error": "This token belongs to another distribution center."
        }), 403
    
    
    if token.token_status != "active":
        return jsonify({"error": f"Token status is {token.token_status}"}), 400

    token.token_status = "used"

    db.session.commit()

    log_action(
            current_user_id,
            "Aid Collected",
            f"{officer.first_name} {officer.second_name} distributed aid to beneficiary {token.user_id}"
        )

    return jsonify({
     "message": "Aid collected successfully",
     "beneficiary_id": token.user_id

    }), 200


@officer_bp.route('/download-beneficiaries', methods=['GET'])
@token_required
def download_beneficiaries(current_user_id):
    officer = Users.query.get(current_user_id)
    if not officer.assigned_center_id:
        return jsonify({"error": "You must be assigned to this distribution center to download beneficiaries."}), 403

    active_session = DistributionCenter.query.filter_by(is_active=True).first()
    if not active_session:
        return jsonify({"error": "No active distribution session found."}), 404

    session_tokens = AidTokens.query.filter_by(distribution_center_id=active_session.id).all()
    data = []

    for token in session_tokens:
        user = Users.query.get(token.user_id)
        # Using the foreign key relationship correctly
        household = Household.query.filter_by(user_id=token.user_id).first()
        
        if user:
            data.append({
                "national_id": user.national_id,
                "name": f"{user.first_name} {user.second_name}",
                "aid_token": token.aid_token, 
                "token_status": token.token_status,
                "total_members": household.total_members if household else 0,
                "dependents_count": household.dependents_count if household else 0,
                "income_level": household.income_level if household else 0,
                "disability_present": household.disability_present if household else False,
                "distribution_center": active_session.aid_center_name
            }) 

    return jsonify({
        "message": "Data downloaded successfully",
        "session_name": active_session.aid_center_name,
        "beneficiaries": data
    }), 200

@officer_bp.route('/recent-activity', methods=['GET'])
@token_required  
def recent_activity(current_user_id):
    officer = Users.query.get(current_user_id)
    if not officer.assigned_center_id:
        return jsonify({"error": "You must be assigned to this distribution center to view recent activity."}), 403
    logs = AuditLog.query\
        .order_by(AuditLog.timestamp.desc())\
        .limit(10)\
        .all()

    data = []
    for log in logs:
        data.append({
            "action": log.action,
            "description": log.details, 
            "time": log.timestamp.strftime("%H:%M")
        })

    return jsonify(data), 200