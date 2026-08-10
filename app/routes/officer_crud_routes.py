import uuid
from flask import Blueprint, jsonify, request
from app.Admin.audit import log_action
from app.models import AidTokens, AuditLog, DistributionCenter, Household, Users
from app import db
from datetime import datetime
from app.tokens import token_required
from app.utilis.sessions import auto_expire_session
from app.utilis.timezone import make_eat, now_eat

officer_bp = Blueprint("officer_bp", __name__)


@officer_bp.route("/start-distribution-session", methods=["POST"])
@token_required
def start_distribution_session(current_user_id):
    worker = Users.query.get(current_user_id)
    if not worker.assigned_center_id:
        return jsonify({"error": "You must be assigned to a distribution center."}), 403
    
    center = DistributionCenter.query.get(worker.assigned_center_id)
    auto_expire_session(center)

    if center.is_active:
        return jsonify({"error": "A distribution session is already active for this center."}), 400

    center.is_active = True
    center.start_time = now_eat()
    center.current_session_id = str(uuid.uuid4())
    center.expiry_time = None

    expiry_time_str = request.json.get("expiry_time")
    if expiry_time_str:
        naive_expiry_time = datetime.strptime(expiry_time_str, "%Y-%m-%d %H:%M:%S")
        center.expiry_time = make_eat(naive_expiry_time)

    db.session.commit()

    log_action(
        current_user_id,
        "Distribution Session Started",
        f"Officer {worker.first_name} {worker.second_name} started distribution session at center {center.aid_center_name}",
    )

    return (
        jsonify(
            {
                "message": f"Distribution session started for {center.aid_center_name}",
                "center_id": center.id,
                "session_id": center.current_session_id,
            }
        ),
        200,
    )


@officer_bp.route("/end-distribution-session", methods=["POST"])
@token_required
def end_distribution_session(current_user_id):
    worker = Users.query.get(current_user_id)
    if not worker or not worker.assigned_center_id:
        return jsonify({"error": "You must be assigned to a distribution center."}), 403

    center = DistributionCenter.query.get(worker.assigned_center_id)
    if not center:
        return jsonify({"error": "Distribution center not found."}), 404

    if not center.is_active:
        return jsonify({"message": "There is no active distribution session for this center."}), 400

    current_session = center.current_session_id

    AidTokens.query.filter(
        AidTokens.distribution_center_id == center.id,
        AidTokens.session_id == current_session,
        AidTokens.token_status.in_(["pending", "active"]),
    ).update(
        {"token_status": "expired"},
        synchronize_session=False,
    )

    center.is_active = False
    center.start_time = None
    center.expiry_time = None
    center.current_session_id = None

    db.session.commit()

    log_action(
        current_user_id,
        "Distribution Session Ended",
        f"Officer {worker.first_name} {worker.second_name} ended distribution session at center {center.aid_center_name}",
    )

    return jsonify({"message": f"Distribution session for {center.aid_center_name} has ended successfully. All unused tokens have been expired."}), 200


@officer_bp.route("/verify-token", methods=["POST"])
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
        return jsonify({"error": "This token belongs to another distribution center."}), 403

    center = DistributionCenter.query.get(token.distribution_center_id)
    if not center:
        return jsonify({"error": "Distribution center not found"}), 404

    auto_expire_session(center)
    if center.expiry_time and center.expiry_time < now_eat():
        token.token_status = "expired"
        db.session.commit()
        return jsonify({"error": "Token expired"}), 400

    if token.token_status in ["used", "expired"]:
        return jsonify({"error": f"Token status is {token.token_status}"}), 400

    user = Users.query.get(token.user_id)
    household = Household.query.filter_by(user_id=token.user_id).first()

    if not user:
        return jsonify({"error": "Beneficiary not found"}), 404

    log_action(
        current_user_id,
        "Token Verified",
        f"Verified token {token.aid_token} for beneficiary {user.id}",
    )

    return (
        jsonify(
            {
                "message": "Token verified successfully",
                "beneficiary": {
                    "id": user.id,
                    "name": f"{user.first_name} {user.second_name}",
                    "national_id": user.national_id,
                    "total_members": household.total_members if household else 0,
                    "dependents_count": household.dependents_count if household else 0,
                    "income_level": household.income_level if household else 0,
                    "disability_present": household.disability_present if household else False,
                    "vulnerability_score": household.vulnerability_score if household else 0,
                    "distribution_center": center.aid_center_name,
                    "aid_token": token.aid_token,
                    "token_status": token.token_status,
                    "aid_collected": token.token_status == "used",
                },
            }
        ),
        200,
    )


@officer_bp.route("/collect-aid", methods=["POST"])
@token_required
def collect_aid(current_user_id):
    token_value = request.json.get("aid_token")
    if not token_value:
        return jsonify({"error": "Token required"}), 400

    officer = Users.query.get(current_user_id)
    token = AidTokens.query.filter_by(aid_token=token_value).first()

    if not token:
        return jsonify({"error": "Invalid token"}), 404

    if token.distribution_center_id != officer.assigned_center_id:
        return jsonify({"error": "This token belongs to another distribution center."}), 403

    center = DistributionCenter.query.get(token.distribution_center_id)
    auto_expire_session(center)

    if not center or token.session_id != center.current_session_id:
        return jsonify({"error": "Token does not belong to the current distribution session."}), 400

    if token.token_status != "active":
        return jsonify({"error": f"Token status is {token.token_status}"}), 400

    token.token_status = "used"
    db.session.commit()

    log_action(
        current_user_id,
        "Aid Collected",
        f"{officer.first_name} {officer.second_name} distributed aid to beneficiary {token.user_id}",
    )

    return jsonify({"message": "Aid collected successfully", "beneficiary_id": token.user_id}), 200


@officer_bp.route("/download-beneficiaries", methods=["GET"])
@token_required
def download_beneficiaries(current_user_id):
    officer = Users.query.get(current_user_id)
    if not officer or not officer.assigned_center_id:
        return jsonify({"error": "You must be assigned to a distribution center to download beneficiaries."}), 403

    center = DistributionCenter.query.get(officer.assigned_center_id)
    if not center:
        return jsonify({"error": "Distribution center not found."}), 404

    if not center.is_active or not center.current_session_id:
        return (
            jsonify(
                {
                    "message": "No active distribution session.",
                    "session_name": center.aid_center_name,
                    "beneficiaries": [],
                    "count": 0,
                }
            ),
            200,
        )

    session_tokens = AidTokens.query.filter_by(
        distribution_center_id=center.id,
        session_id=center.current_session_id,
    ).all()

    beneficiaries = []
    for token in session_tokens:
        if token.user_id is None:
            continue

        user = Users.query.get(token.user_id)
        household = Household.query.filter_by(user_id=token.user_id).first()

        if not user:
            continue

        beneficiaries.append(
            {
                "national_id": user.national_id,
                "name": f"{user.first_name} {user.second_name}",
                "aid_token": token.aid_token,
                "token_status": token.token_status,
                "total_members": household.total_members if household else 0,
                "dependents_count": household.dependents_count if household else 0,
                "income_level": household.income_level if household else 0,
                "disability_present": household.disability_present if household else False,
                "vulnerability_score": household.vulnerability_score if household else 0,
                "distribution_center": center.aid_center_name,
            }
        )

    return (
        jsonify(
            {
                "message": "Beneficiaries downloaded successfully.",
                "session_name": center.aid_center_name,
                "beneficiaries": beneficiaries,
                "count": len(beneficiaries),
            }
        ),
        200,
    )


@officer_bp.route("/recent-activity", methods=["GET"])
@token_required
def recent_activity(current_user_id):
    officer = Users.query.get(current_user_id)
    if not officer.assigned_center_id:
        return jsonify({"error": "You must be assigned to this distribution center to view recent activity."}), 403

    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
    data = []
    for log in logs:
        data.append(
            {
                "action": log.action,
                "description": log.details,
                "time": log.timestamp.strftime("%H:%M"),
            }
        )

    return jsonify(data), 200


@officer_bp.route("/sync", methods=["POST"])
@token_required
def sync_offline_records(current_user_id):
    payload = request.get_json()
    if not payload or "records" not in payload:
        return jsonify({"error": "No records supplied"}), 400

    records = payload["records"]
    synced = []
    failed = []

    officer = Users.query.get(current_user_id)
    if officer is None:
        return jsonify({"error": "Officer not found"}), 404

    for record in records:
        token = AidTokens.query.filter_by(aid_token=record["aid_token"]).first()
        if token is None:
            failed.append(
                {
                    "local_id": record.get("local_id"),
                    "aid_token": record["aid_token"],
                    "reason": "Token not found",
                }
            )
            continue

        if token.token_status == "used":
            failed.append(
                {
                    "local_id": record.get("local_id"),
                    "aid_token": record["aid_token"],
                    "reason": "Already redeemed",
                }
            )
            continue

        token.token_status = "used"
        token.redeemed_at = now_eat()
        token.redeemed_by = current_user_id

        synced.append(record["local_id"])
        log_action(officer.id, "Offline Synchronization", f"Synced token {record['aid_token']}")

    db.session.commit()
    return (
        jsonify(
            {
                "message": "Synchronization completed.",
                "synced": synced,
                "failed": failed,
                "total_received": len(records),
                "total_synced": len(synced),
                "total_failed": len(failed),
            }
        ),
        200,
    )