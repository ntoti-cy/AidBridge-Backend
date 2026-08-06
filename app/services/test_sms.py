from flask import Blueprint, jsonify

from app.services.sms_services import send_sms


test_bp = Blueprint("test", __name__)

@test_bp.route("/test-sms")
def test_sms():
    success = send_sms(
        "+254788600101",
        "Hello from AidBridge!"
    )

    return jsonify({"success": success})