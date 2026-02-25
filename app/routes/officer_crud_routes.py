import datetime

from flask import Blueprint, jsonify, request
from app.models import  Users, DistributionSession
from app import db



officer_bp = Blueprint('officer_bp', __name__)

@officer_bp.route('/start-distribution-session', methods=['POST'])
def start_distribution_session():
    # Logic to start a distribution session
    
    aid_center_name = request.json.get('aid_center_name')
    expiry_time = request.json.get('expiry_time') 
    
    if not aid_center_name or not expiry_time:
        return "Missing required fields", 400
    
    session= DistributionSession(
        aid_center_name=aid_center_name,
        expiry_time=datetime.strptime(expiry_time, '%Y-%m-%d %H:%M:%S'),
        is_active=True
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        "message": "Distribution session started", 
        "session_id": session.id}), 200
   
@officer_bp.route('/end-distribution-session/<int:session_id>', methods=['POST'])
def end_distribution_session(session_id):
    session = DistributionSession.query.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    #Expires all unused active aid tokens
    Users.query.filter_by(
        distribution_sessions=session_id,token_status='active'
        ).update({"token_status": "expired",
                  "token_expires_at": datetime.datetime.utcnow()})
    
    session.is_active = False
    db.session.commit()

    return jsonify({"message": "Distribution session ended"}), 200