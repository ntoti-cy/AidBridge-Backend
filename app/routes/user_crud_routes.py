from datetime import datetime
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash
from app import db
from app.Admin.audit import log_action
from app.models import AidTokens, DistributionCenter, Household, Users, UssdSession
from app.routes.auth_routes import register
from app.tokens import generate_aid_token, profile_required, token_required

user_bp = Blueprint(
    "user_bp",
    __name__,
)


def get_user_active_center(user_id):
    household = Household.query.filter_by(user_id=user_id).first()
    if not household or not household.center_id:
        return None, "Please complete your profile and select a distribution center."

    center = DistributionCenter.query.get(household.center_id)
    if not center:
        return None, "Your selected distribution center is no longer available."

    if not center.is_active:
        return (
            None,
            "Aid collection is not currently open at your distribution center.",
        )

    if center.expiry_time and center.expiry_time < datetime.utcnow():
        return None, "Aid collection has ended at your distribution center."

    return center, None


# USSD
@user_bp.route("/callback", methods=["POST"])
def ussd_callback():
    session_id = request.form.get("sessionId")
    contact = request.form.get("phoneNumber")
    text = request.form.get("text")

    response = ""

    if text:
        parts = text.split("*")
        if parts[-1] == "0":
            if len(parts) > 1:
                parts = parts[:-2]
            else:
                parts = []
            text = "*".join(parts)

    parts = text.split("*") if text else []

    if text == "":
        response = "CON Welcome to Aidbridge Aid Access System\n"
        response += "Bridging Aid to the last Mile\n"
        response += "1.Register\n"
        response += "2.Login\n"
        response += "3.Exit"

    elif parts[0] == "1":
        if len(parts) == 1:
            response = "CON Enter First Name:"
        elif len(parts) == 2:
            response = "CON Enter Second Name:"
        elif len(parts) == 3:
            response = "CON Enter National ID:"
        elif len(parts) == 4:
            response = "CON Set Your Password:"
        elif len(parts) == 5:
            first_name = parts[1]
            second_name = parts[2]

            try:
                national_id = int(parts[3])
            except ValueError:
                return "END Invalid National ID.", 200

            password = parts[4]

            data = {
                "first_name": first_name,
                "second_name": second_name,
                "national_id": national_id,
                "contact": contact,
                "password": password,
            }

            with current_app.test_request_context(
                "/register", method="POST", json=data
            ):
                register_response = register()
                if register_response[1] != 201:
                    return f"END {register_response[0].json.get('error')}", 200

            response = "END Registration Successful. Please Login."

    elif parts[0] == "2":
        if len(parts) == 1:
            response = "CON Enter Password:"

        elif len(parts) == 2:
            password = parts[1]
            user = Users.query.filter_by(contact=contact).first()

            if not user or not check_password_hash(user.password, password):
                return "END Invalid Credentials.", 200

            session = UssdSession.query.filter_by(session_id=session_id).first()
            if not session:
                session = UssdSession(
                    session_id=session_id,
                    user_id=user.id,
                    authenticated=True,
                    last_active=datetime.utcnow(),
                )
                db.session.add(session)
            else:
                session.user_id = user.id
                session.authenticated = True
                session.last_active = datetime.utcnow()
            db.session.commit()

            response = f"CON Welcome {user.first_name}\n"
            response += "1.Request Aid Token\n"
            response += "2.Check Token Status\n"
            response += "0.Back\n"
            response += "9.Exit"

        elif len(parts) == 3:
            choice = parts[2]
            session = UssdSession.query.filter_by(session_id=session_id).first()
            if not session or not session.authenticated:
                return "END Session expired. Please login again.", 200

            user = Users.query.get(session.user_id)

            if choice == "1":
                center, err_msg = get_user_active_center(user.id)
                if err_msg:
                    return f"END {err_msg}", 200

                existing_token = (
                    AidTokens.query.filter_by(
                        user_id=user.id, distribution_center_id=center.id
                    )
                    .order_by(AidTokens.token_issued_at.desc())
                    .first()
                )

                if existing_token:
                    if existing_token.token_status == "active":
                        return (
                            "END You already have an active token for this center session.",
                            200,
                        )
                    elif existing_token.token_status == "used":
                        return (
                            "END You have already used your token for this center session.",
                            200,
                        )
                    elif existing_token.token_status == "expired":
                        return "END Distribution session has ended.", 200

                try:
                    token = generate_aid_token(user)
                    new_token = AidTokens(
                        user_id=user.id,
                        aid_token=token,
                        token_status="active",
                        token_issued_at=datetime.utcnow(),
                        distribution_center_id=center.id,
                    )
                    db.session.add(new_token)
                    db.session.commit()

                    log_action(
                        user.id,
                        "Token Issued",
                        f"Aid token {token} issued to {user.first_name} {user.second_name}",
                    )

                    print(f"Send SMS to {user.contact}: Your Aid Token is {token}")
                    response = "END Token sent via SMS."
                except Exception as e:
                    db.session.rollback()
                    return "END Failed to generate token. Try again later.", 200

            elif choice == "2":
                center, err_msg = get_user_active_center(user.id)
                if err_msg:
                    return f"END {err_msg}", 200

                token = (
                    AidTokens.query.filter_by(
                        user_id=user.id, distribution_center_id=center.id
                    )
                    .order_by(AidTokens.token_issued_at.desc())
                    .first()
                )

                if not token:
                    return (
                        "END You have not requested a token for this active session.",
                        200,
                    )

                response = f"END Token: {token.aid_token}\nStatus: {token.token_status}"

            elif choice == "9":
                response = "END Thank you for trusting AidBridge."
                db.session.delete(session)
                db.session.commit()

            else:
                response = "END Invalid choice."

    elif parts[0] == "9":
        response = "END Thank you for trusting AidBridge."
        session = UssdSession.query.filter_by(session_id=session_id).first()
        if session:
            db.session.delete(session)
            db.session.commit()

    else:
        response = "END Invalid option."

    return response, 200


@user_bp.route("/request-token", methods=["POST", "GET"])
@token_required
@profile_required
def request_smartphone_token(current_user_id):
    user = Users.query.get(current_user_id)
    if not user:
        return jsonify({"error": "Beneficiary not found"}), 404

    center, err_msg = get_user_active_center(user.id)
    if err_msg:
        return jsonify({"error": err_msg}), 400

    existing_token = (
        AidTokens.query.filter_by(user_id=user.id, distribution_center_id=center.id)
        .order_by(AidTokens.token_issued_at.desc())
        .first()
    )

    if existing_token:
        if existing_token.token_status == "active":
            return (
                jsonify(
                    {
                        "message": "Retrieved existing active token.",
                        "aid_token": existing_token.aid_token,
                        "token_status": existing_token.token_status,
                        "center_name": center.aid_center_name,
                        "expiry_time": (
                            center.expiry_time.isoformat()
                            if center.expiry_time
                            else None
                        ),
                    }
                ),
                200,
            )

        elif existing_token.token_status == "used":
            return (
                jsonify(
                    {
                        "error": "You have already received your aid for this center session."
                    }
                ),
                400,
            )

        elif existing_token.token_status == "expired":
            return (
                jsonify({"error": "Your token for this center session has expired."}),
                400,
            )

    try:
        token_string = generate_aid_token(user)

        new_token = AidTokens(
            user_id=user.id,
            aid_token=token_string,
            token_status="active",
            token_issued_at=datetime.utcnow(),
            distribution_center_id=center.id,
        )
        db.session.add(new_token)
        db.session.commit()

        log_action(
            user.id,
            "Token Issued",
            f"Aid token {token_string} issued to smartphone user {user.first_name} {user.second_name}",
        )

        return (
            jsonify(
                {
                    "message": "Token generated successfully",
                    "aid_token": token_string,
                    "token_status": "active",
                    "center_name": center.aid_center_name,
                    "expiry_time": (
                        center.expiry_time.isoformat() if center.expiry_time else None
                    ),
                }
            ),
            201,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to generate token.", "details": str(e)}), 500


@user_bp.route("/token-history", methods=["GET"])
@token_required
def get_token_history(current_user_id):
    tokens = (
        AidTokens.query.filter_by(user_id=current_user_id)
        .order_by(AidTokens.token_issued_at.desc())
        .all()
    )

    history_data = []
    for token in tokens:
        center = (
            DistributionCenter.query.get(token.distribution_center_id)
            if token.distribution_center_id
            else None
        )

        history_data.append(
            {
                "id": token.id,
                "aid_token": token.aid_token,
                "token_status": token.token_status,
                "token_issued_at": (
                    token.token_issued_at.strftime("%Y-%m-%d %H:%M:%S")
                    if token.token_issued_at
                    else None
                ),
                "center_name": (
                    center.aid_center_name if center else "General Distribution"
                ),
                "expiry_time": (
                    center.expiry_time.isoformat()
                    if center and center.expiry_time
                    else None
                ),
            }
        )

    return (
        jsonify(
            {"message": "Token history retrieved successfully", "history": history_data}
        ),
        200,
    )


@user_bp.route("/token-status", methods=["GET"])
@token_required
def get_token_status(current_user_id):

    user = Users.query.get(current_user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    if user.role != "beneficiary":
        return jsonify({"error": "Only beneficiaries can access token status"}), 403


    # Get beneficiary selected center
    household = Household.query.filter_by(user_id=user.id).first()

    if not household or not household.center_id:
        return jsonify(
            {
                "error": "No distribution center selected. Please complete your profile."
            }
        ), 400


    center = DistributionCenter.query.get(household.center_id)

    if not center:
        return jsonify(
            {
                "error": "Selected distribution center no longer exists."
            }
        ), 404


    # Get latest token for this beneficiary at this center
    token = (
        AidTokens.query.filter_by(
            user_id=user.id,
            distribution_center_id=center.id
        )
        .order_by(AidTokens.token_issued_at.desc())
        .first()
    )


    if not token:
        return jsonify(
            {
                "has_token": False,
                "message": "No active aid token found.",
                "center_name": center.aid_center_name
            }
        ), 200


    return jsonify(
        {
            "has_token": True,
            "aid_token": token.aid_token,
            "token_status": token.token_status,
            "center_id": center.id,
            "center_name": center.aid_center_name,
            "token_issued_at": (
                token.token_issued_at.isoformat()
                if token.token_issued_at
                else None
            ),
            "expiry_time": (
                center.expiry_time.isoformat()
                if center.expiry_time
                else None
            )
        }
    ), 200