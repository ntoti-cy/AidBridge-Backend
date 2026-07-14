from datetime import datetime
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash
from app import db
from app.Admin.audit import log_action
from sqlalchemy.orm.attributes import flag_modified
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

def get_or_create_ussd_session(session_id):
    session = UssdSession.query.filter_by(
        session_id=session_id
    ).first()

    if session and session.last_active and (datetime.utcnow() - session.last_active).total_seconds() > 300:
        db.session.delete(session)
        db.session.commit()
        session = None

    if not session:
        session = UssdSession(
            session_id=session_id,
            current_menu="main",
            profile_step=0,
            profile_data={},
            last_active=datetime.utcnow()
        )

        db.session.add(session)
        db.session.commit()
    else:
        session.last_active = datetime.utcnow()

        if session.profile_data is None:
            session.profile_data = {}
        db.session.commit()

    return session

def get_ussd_centers_menu():
    centers = (
        DistributionCenter.query
        .filter_by(is_active=True)
        .order_by(DistributionCenter.id)
        .all()
    )

    if not centers:
        return None, "END No active distribution centers available."

    menu = "CON Select Distribution Center:\n"

    for index, center in enumerate(centers, start=1):
        menu += f"{index}. {center.aid_center_name}\n"

    return centers, menu

#USSD
@user_bp.route("/callback", methods=["POST"])
def ussd_callback():
    session_id = request.form.get("sessionId")
    contact = request.form.get("phoneNumber")
    text = request.form.get("text")

    response = ""

    if text:
        parts = text.split("*")
        if parts[-1] == "0":
            # Check if we are inside the profile wizard and can go back a step
            session_check = UssdSession.query.filter_by(session_id=session_id).first()
            if session_check and session_check.last_active and (datetime.utcnow() - session_check.last_active).total_seconds() > 300:
                db.session.delete(session_check)
                db.session.commit()
                return "END Session expired. Please login again.", 200

            if session_check and session_check.current_menu == "profile" and session_check.profile_step > 1:
                if session_check.profile_step == 2:
                    session_check.profile_data.pop("total_members", None)
                    flag_modified(session_check, "profile_data")
                    
                elif session_check.profile_step == 3:
                    session_check.profile_data.pop("dependents_count", None)
                    flag_modified(session_check, "profile_data")
                elif session_check.profile_step == 4:
                    session_check.profile_data.pop("disability_present", None)
                    flag_modified(session_check, "profile_data")
                elif session_check.profile_step == 5:
                    session_check.profile_data.pop("income_level", None)
                    flag_modified(session_check, "profile_data")
                
                session_check.profile_step -= 1
                session_check.last_active = datetime.utcnow()
                db.session.commit()
                # Pop back up one part from the USSD string representation
                parts = parts[:-2]
                text = "*".join(parts)
            else:
                if len(parts) > 1:
                    parts = parts[:-2]
                else:
                    parts = []
                text = "*".join(parts)

    parts = text.split("*") if text else []
    current_answer = parts[-1] if parts else ""

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

            if not user:
                return "END User not found"
            if not check_password_hash(user.password, password):
                return "END Invalid Password.", 200

            session = get_or_create_ussd_session(session_id)
           

            session.user_id = user.id
            session.authenticated = True
            session.current_menu = "dashboard"
            session.profile_step = 0
            session.profile_data = {}
            session.last_active = datetime.utcnow()
            db.session.commit()

            household = Household.query.filter_by(user_id=user.id).first()
            response = f"CON Welcome {user.first_name}\n"
            if household and household.is_profile_complete:
                response += "1.Request Aid Token\n"
                response += "2.Check Token Status\n"
                response += "9.Exit"
            else:
                response += "1.Complete Profile\n"
                response += "9.Exit"

        elif len(parts) >= 3:
            choice = parts[2]
            session = get_or_create_ussd_session(session_id)
            if not session or not session.authenticated:
                return "END Session expired. Please login again.", 200

            
            user = Users.query.get(session.user_id)
            household = Household.query.filter_by(user_id=user.id).first()
            is_complete = household and household.is_profile_complete

            # Route choice based on profile completion status
            if not is_complete:
                if choice == "1":
                    if not household:
                        household = Household(user_id=user.id)
                        db.session.add(household)
                        session.last_active = datetime.utcnow()
                        db.session.commit()

                    if session.profile_step == 0:
                        session.current_menu = "profile"
                        session.profile_step = 1
                        session.profile_data = {}
                        session.last_active = datetime.utcnow()
                        db.session.commit()
                        response = "CON Enter total household members:\n0.Back"

                    elif session.profile_step == 1:
                        try:
                            total_members = int(current_answer)
                            if total_members < 1:
                                return "END Household members must be at least 1.", 200

                            data = session.profile_data or {}
                            data["total_members"] = total_members
                            session.profile_data = data
                            flag_modified(session,"profile_data")
                            session.profile_step = 2
                            session.last_active = datetime.utcnow()
                            db.session.commit()
                            response = "CON Enter number of dependents:\n0.Back"
                        except ValueError:
                            return "END Invalid number.", 200

                    elif session.profile_step == 2:
                        try:
                            dependents = int(current_answer)
                            if dependents < 0:
                                return "END Dependents cannot be negative.", 200
                            if dependents > session.profile_data.get("total_members", 0):
                                return "END Dependents cannot exceed household members.", 200

                            data = session.profile_data or {}
                            data["dependents_count"] = dependents
                            session.profile_data = data
                            flag_modified(session,"profile_data")
                            session.profile_step = 3
                            session.last_active = datetime.utcnow()
                            db.session.commit()
                            response = "CON Disability present?\n1.Yes\n2.No\n0.Back"
                        except ValueError:
                            return "END Invalid number.", 200

                    elif session.profile_step == 3:
                        disability = current_answer
                        if disability not in ["1", "2"]:
                            return "END Invalid choice.", 200

                        data = session.profile_data or {}
                        data["disability_present"] = (disability == "1")
                        session.profile_data = data
                        flag_modified(session,"profile_data")
                        session.profile_step = 4
                        session.last_active = datetime.utcnow()
                        db.session.commit()
                        response = "CON Enter estimated monthly income (KES):\n0.Back"

                    elif session.profile_step == 4:
                        try:
                            income = float(current_answer)
                            if income < 0:
                                return "END Income cannot be negative.", 200

                            data = session.profile_data or {}
                            data["income_level"] = income
                            session.profile_data = data
                            flag_modified(session,"profile_data")
                            session.profile_step = 5
                            session.last_active = datetime.utcnow()
                            db.session.commit()

                            centers, menu = get_ussd_centers_menu()
                            if not centers:
                                return menu, 200
                            
                            return menu + "0.Back", 200
                        except ValueError:
                            return "END Invalid income.", 200

                    elif session.profile_step == 5:
                        try:
                            centers, _ = get_ussd_centers_menu()
                            selected = int(current_answer) - 1
                            if selected < 0 or selected >= len(centers):
                                return "END Invalid distribution center.", 200
                            center = centers[selected]

                            profile = session.profile_data or {}
                            
                            if not all(key in profile for key in[
                                "total_members",
                                "dependents_count",
                                "disability_present",
                                "income_level"
                            ]):
                                return "END Profile data incomplete.Please restart profile.",200
                                
                            

                            household.total_members = profile.get("total_members",1)
                            household.dependents_count = profile.get("dependents_count",0)
                            household.disability_present = profile.get("disability_present",False)
                            household.income_level = profile.get("income_level",0)

                            household.center_id = center.id
                            household.calculate_score()
                            household.is_profile_complete = True
                            user.assigned_center_id = center.id

                            

                            session.profile_step = 0
                            session.current_menu = "dashboard"
                            session.profile_data = {}
                            session.last_active = datetime.utcnow()
                            db.session.commit()

                            log_action(
                                user.id,
                                "Profile Completed",
                                f"{user.first_name} selected {center.aid_center_name} via USSD."
                            )

                            response = (
                                "END Profile completed successfully.\n"
                                "Login now to request your aid token."
                            )
                        except Exception as e:
                            db.session.rollback()
                            print("PROFILE SAVE ERROR:", e)
                            return "END Failed to save profile.", 200

                elif choice == "9":
                    response = "END Thank you for trusting AidBridge."
                    db.session.delete(session)
                    db.session.commit()
                else:
                    response = "END Invalid choice."
            
            else:
                # Profile is complete; map choices 1, 2, and 9
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
                            return "END You already have an active token .", 200
                        elif existing_token.token_status == "used":
                            return "END You have already used your token.", 200
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
                        session.last_active = datetime.utcnow()
                        db.session.commit()

                        log_action(
                            user.id,
                            "Token Issued",
                            f"Aid token {token} issued to {user.first_name} {user.second_name}",
                        )

                        print(f"Send SMS to {user.contact}: Your Aid Token is {token}")
                        response = "END Token sent via SMS."
                    except Exception :
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
                        return "END You have not requested a token for this active session.", 200

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