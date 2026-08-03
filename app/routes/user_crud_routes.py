from datetime import datetime
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash
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
    session = UssdSession.query.filter_by(session_id=session_id).first()

    if (
        session
        and session.last_active
        and (datetime.utcnow() - session.last_active).total_seconds() > 300
    ):
        db.session.delete(session)
        db.session.commit()
        session = None

    if not session:
        session = UssdSession(
            session_id=session_id,
            current_menu="main",
            profile_step=0,
            profile_data={},
            last_active=datetime.utcnow(),
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
        DistributionCenter.query.filter_by(is_active=True)
        .order_by(DistributionCenter.id)
        .all()
    )

    if not centers:
        return None, "END No active distribution centers available."

    menu = "CON Select Distribution Center:\n"

    for index, center in enumerate(centers, start=1):
        menu += f"{index}. {center.aid_center_name}\n"

    return centers, menu


# USSD
@user_bp.route("/callback", methods=["POST"])
def ussd_callback():
    session_id = request.form.get("sessionId")
    contact = request.form.get("phoneNumber")
    if contact:
        contact = contact.replace("+", "").replace(" ", "")
    text = request.form.get("text")

    response = ""

    if text:
        parts = text.split("*")
        if parts[-1] == "0":
            session_check = UssdSession.query.filter_by(session_id=session_id).first()
            if (
                session_check
                and session_check.last_active
                and (datetime.utcnow() - session_check.last_active).total_seconds()
                > 300
            ):
                db.session.delete(session_check)
                db.session.commit()
                return "END Session expired. Please login again.", 200

            # Handle going back a step in profile wizard
            if (
                session_check
                and session_check.current_menu == "profile"
                and session_check.profile_step > 1
            ):
                if session_check.profile_step == 2:
                    session_check.profile_data.pop("total_members", None)
                elif session_check.profile_step == 3:
                    session_check.profile_data.pop("dependents_count", None)
                elif session_check.profile_step == 4:
                    session_check.profile_data.pop("disability_present", None)
                elif session_check.profile_step == 5:
                    session_check.profile_data.pop("income_level", None)

                flag_modified(session_check, "profile_data")
                session_check.profile_step -= 1
                session_check.last_active = datetime.utcnow()
                db.session.commit()
                parts = parts[:-2]
                text = "*".join(parts)

            # Handle going back out of change password wizard
            elif session_check and session_check.current_menu == "change_password":
                session_check.current_menu = "dashboard"
                session_check.profile_step = 0
                session_check.profile_data = {}
                session_check.last_active = datetime.utcnow()
                db.session.commit()
                parts = parts[:-2]
                text = "*".join(parts)

            # Handle going back out of forgot password wizard
            elif session_check and session_check.current_menu == "forgot_password":
                if session_check.profile_step > 1:
                    session_check.profile_data.pop("new_password", None)
                    flag_modified(session_check, "profile_data")
                    session_check.profile_step -= 1
                    session_check.last_active = datetime.utcnow()
                    db.session.commit()
                    parts = parts[:-2]
                    text = "*".join(parts)
                else:
                    db.session.delete(session_check)
                    db.session.commit()
                    return "END Returning to main menu. Please dial in again.", 200

            else:
                if len(parts) > 1:
                    parts = parts[:-2]
                else:
                    parts = []
                text = "*".join(parts)

    parts = text.split("*") if text else []
    current_answer = parts[-1] if parts else ""

    # Root Level Menu
    if text == "":
        response = "CON Welcome to Aidbridge Aid Access System\n"
        response += "Bridging Aid to the last Mile\n"
        response += "1.Register\n"
        response += "2.Login\n"
        response += "3.Forgot Password\n"
        response += "9.Exit"

    # Registration
    elif parts[0] == "1":
        if len(parts) == 1:
            return "CON Enter First Name:"

        elif len(parts) == 2:
            first_name = parts[1].strip()
            if not first_name.isalpha():
                return "CON First name must contain only letters.\nEnter First Name:"
            return "CON Enter Second Name:"

        elif len(parts) == 3:
            first_name = parts[1].strip()
            second_name = parts[2].strip()
            if not second_name.isalpha():
                return "CON Second name must contain only letters.\nEnter Second Name:"
            return "CON Enter National ID:"

        elif len(parts) == 4:
            national_id_str = parts[3].strip()
            if not national_id_str.isdigit():
                return "CON National ID must contain only numbers.\nEnter National ID:"

            # Check if National ID already exists in database
            existing_nid = Users.query.filter_by(national_id=national_id_str).first()
            if existing_nid:
                return "CON National ID already exists.\nEnter National ID:"

            return "CON Set Your Password (min 6 characters):"

        elif len(parts) == 5:
            first_name = parts[1].strip()
            second_name = parts[2].strip()
            national_id = parts[3].strip()
            password = parts[4].strip()

            if len(password) < 6:
                return "CON Password must be at least 6 characters.\nSet Your Password:"

            data = {
                "first_name": first_name,
                "second_name": second_name,
                "national_id": national_id,
                "contact": contact,
                "email": f"{contact}@aidbridge.ussd",  # Fallback dummy email for USSD registrations if email is required
                "password": password,
            }

            with current_app.test_request_context(
                "/register", method="POST", json=data
            ):
                register_response = register()
                if register_response[1] != 201:
                    err_msg = "Registration failed."
                    try:
                        res_json = register_response[0].get_json()
                        if res_json and "errors" in res_json:
                            # Flatten field-specific error messages from validation dictionary
                            flat_errs = []
                            for field_errs in res_json["errors"].values():
                                flat_errs.extend(field_errs)
                            err_msg = " ".join(flat_errs)
                        elif res_json and "error" in res_json:
                            err_msg = res_json["error"]
                    except Exception:
                        pass
                    return f"END Error: {err_msg}", 200

            return "END Registration Successful. Please Login."

    # Login
    elif parts[0] == "2":
        # Initial login password prompt
        if len(parts) == 1:
            response = "CON Enter Password:"

        elif len(parts) == 2:
            password = parts[1]
            user = Users.query.filter_by(contact=contact).first()

            if not user:
                return "END User not found", 200
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
                response += "3.View Profile\n"
                response += "4.Change Password\n"
                response += "9.Exit"
            else:
                response += "1.Complete Profile\n"
                response += "9.Exit"

        # Subsequent authenticated choices or ongoing wizards (length >= 3)
        elif len(parts) >= 3:
            session = get_or_create_ussd_session(session_id)
            if not session or not session.authenticated:
                return "END Session expired. Please login again.", 200

            user = Users.query.get(session.user_id)
            household = Household.query.filter_by(user_id=user.id).first()
            is_complete = household and household.is_profile_complete

            # INTERCEPT: Handle active Change Password multi-step wizard
            if session.current_menu == "change_password":
                try:
                    if session.profile_step == 1:
                        # Evaluating current/old password input (which lives at parts[3] roughly depending on length)
                        old_password = current_answer
                        if not check_password_hash(user.password, old_password):
                            return "END Current password entered is incorrect.", 200

                        session.profile_data = {"old_password_verified": True}
                        flag_modified(session, "profile_data")
                        session.profile_step = 2
                        session.last_active = datetime.utcnow()
                        db.session.commit()
                        return "CON Enter new password:\n0.Back", 200

                    elif session.profile_step == 2:
                        new_password = current_answer
                        if len(new_password) < 6:
                            return "END Password must be at least 6 characters.", 200

                        if check_password_hash(user.password, new_password):
                            return (
                                "END New password must be different from the current password.",
                                200,
                            )

                        data = session.profile_data or {}
                        data["new_password"] = new_password
                        session.profile_data = data
                        flag_modified(session, "profile_data")
                        session.profile_step = 3
                        session.last_active = datetime.utcnow()
                        db.session.commit()
                        return "CON Confirm new password:\n0.Back", 200

                    elif session.profile_step == 3:
                        confirm_password = current_answer
                        new_password = session.profile_data.get("new_password")

                        if confirm_password != new_password:
                            return "END Passwords do not match.", 200

                        user.password = generate_password_hash(new_password)
                        session.current_menu = "dashboard"
                        session.profile_step = 0
                        session.profile_data = {}
                        session.last_active = datetime.utcnow()
                        flag_modified(session, "profile_data")
                        session.authenticated = False
                        db.session.commit()

                        log_action(
                            user.id,
                            "Password Changed",
                            f"{user.first_name} changed their password",
                        )

                        return "END Password changed successfully.", 200
                except Exception as e:
                    db.session.rollback()
                    print("PASSWORD CHANGE ERROR:", e)
                    return "END Failed to change password.", 200

            # Standard Routing for Incomplete Profile
            if not is_complete:
                choice = parts[2]
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
                            flag_modified(session, "profile_data")
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
                            if dependents > session.profile_data.get(
                                "total_members", 0
                            ):
                                return (
                                    "END Dependents cannot exceed household members.",
                                    200,
                                )

                            data = session.profile_data or {}
                            data["dependents_count"] = dependents
                            session.profile_data = data
                            flag_modified(session, "profile_data")
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
                        data["disability_present"] = disability == "1"
                        session.profile_data = data
                        flag_modified(session, "profile_data")
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
                            flag_modified(session, "profile_data")
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
                            if not all(
                                key in profile
                                for key in [
                                    "total_members",
                                    "dependents_count",
                                    "disability_present",
                                    "income_level",
                                ]
                            ):
                                return (
                                    "END Profile data incomplete. Please restart profile.",
                                    200,
                                )

                            household.total_members = profile.get("total_members", 1)
                            household.dependents_count = profile.get(
                                "dependents_count", 0
                            )
                            household.disability_present = profile.get(
                                "disability_present", False
                            )
                            household.income_level = profile.get("income_level", 0)

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
                                f"{user.first_name} selected {center.aid_center_name} via USSD.",
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

            # Standard Routing for Complete Profile
            else:
                choice = parts[2]
                if choice == "1":
                    center, err_msg = get_user_active_center(user.id)
                    if err_msg:
                        return f"END {err_msg}", 200

                    existing_token = (
                        AidTokens.query.filter_by(
                            user_id=user.id,
                            distribution_center_id=center.id,
                            session_id=center.current_session_id,
                        )
                        .order_by(AidTokens.token_issued_at.desc())
                        .first()
                    )

                    if existing_token:
                        if existing_token.token_status == "active":
                            return "END You already have an active token.", 200
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
                            session_id=center.current_session_id,
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
                    except Exception:
                        db.session.rollback()
                        return "END Failed to generate token. Try again later.", 200

                elif choice == "2":
                    center, err_msg = get_user_active_center(user.id)
                    if err_msg:
                        return f"END {err_msg}", 200

                    token = (
                        AidTokens.query.filter_by(
                            user_id=user.id,
                            distribution_center_id=center.id,
                            session_id=center.current_session_id,
                        )
                        .order_by(AidTokens.token_issued_at.desc())
                        .first()
                    )

                    if not token:
                        return (
                            "END You have not requested a token for this active session.",
                            200,
                        )

                    response = (
                        f"END Token: {token.aid_token}\nStatus: {token.token_status}"
                    )

                elif choice == "3":
                    response = (
                        f"END Profile Details\n"
                        f"Name: {user.first_name} {user.second_name}\n"
                        f"National ID: {user.national_id}\n"
                        f"Phone: {user.contact}\n"
                        f"Members: {household.total_members if household else 'N/A'}\n"
                        f"Dependents: {household.dependents_count if household else 'N/A'}\n"
                        f"Disability: {'Yes' if household and household.disability_present else 'No'}\n"
                        f"Income: KES {household.income_level if household else 'N/A'}\n"
                        f"Center: {household.center.aid_center_name if household and household.center else 'Not assigned'}"
                    )

                elif choice == "4":
                    session.current_menu = "change_password"
                    session.profile_step = 1
                    session.last_active = datetime.utcnow()
                    db.session.commit()
                    response = "CON Enter current password:\n0.Back"

                elif choice == "9":
                    response = "END Thank you for trusting AidBridge."
                    db.session.delete(session)
                    db.session.commit()

                else:
                    response = "END Invalid choice."




    # Forgot Password
    elif parts[0] == "3":
        if len(parts) == 1:
            user = Users.query.filter_by(contact=contact).first()
            if not user:
                return "END No account found with this phone number.", 200

            session = get_or_create_ussd_session(session_id)
            session.current_menu = "forgot_password"
            session.profile_step = 1
            session.profile_data = {}
            session.last_active = datetime.utcnow()
            db.session.commit()

            response = "CON Enter new password (min 6 characters):\n0.Back"

        elif len(parts) >= 2:
            session = get_or_create_ussd_session(session_id)
            if not session or session.current_menu != "forgot_password":
                return "END Session expired. Please start again.", 200

            user = Users.query.filter_by(contact=contact).first()
            if not user:
                return "END No account found with this phone number.", 200

            if session.profile_step == 1:
                new_password = current_answer

                if len(new_password) < 6:
                    return "END Password must be at least 6 characters.", 200

                if check_password_hash(user.password, new_password):
                    return (
                        "END New password cannot be the same as the current password.",
                        200,
                    )

                data = session.profile_data or {}
                data["new_password"] = new_password
                session.profile_data = data
                flag_modified(session, "profile_data")
                session.profile_step = 2
                session.last_active = datetime.utcnow()
                db.session.commit()
                response = "CON Confirm new password:\n0.Back"

            elif session.profile_step == 2:
                confirm_password = current_answer
                new_password = session.profile_data.get("new_password")

                if confirm_password != new_password:
                    return "END Passwords do not match.", 200

                try:
                    user.password = generate_password_hash(new_password)
                    if hasattr(user, "requires_password_change") and user.requires_password_change:
                        user.requires_password_change = False

                    log_action(
                        user.id,
                        "Password Reset",
                        f"{user.first_name} reset their password via USSD (forgot password).",
                    )

                    db.session.delete(session)
                    db.session.commit()

                    response = "END Password reset successfully. Please login."
                except Exception as e:
                    db.session.rollback()
                    print("FORGOT PASSWORD ERROR:", e)
                    return "END Failed to reset password. Try again later.", 200
            else:
                response = "END Invalid session state."


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
        AidTokens.query.filter_by(
            user_id=user.id,
            distribution_center_id=center.id,
            session_id=center.current_session_id,
        )
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
            session_id=center.current_session_id,
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
        return (
            jsonify(
                {
                    "error": "No distribution center selected. Please complete your profile."
                }
            ),
            400,
        )

    center = DistributionCenter.query.get(household.center_id)

    if not center:
        return jsonify({"error": "Selected distribution center no longer exists."}), 404

    # Get latest token for this beneficiary at this center
    token = (
        AidTokens.query.filter_by(
            user_id=user.id,
            distribution_center_id=center.id,
            session_id=center.current_session_id,
        )
        .order_by(AidTokens.token_issued_at.desc())
        .first()
    )

    if not token:
        return (
            jsonify(
                {
                    "has_token": False,
                    "message": "No active aid token found.",
                    "center_name": center.aid_center_name,
                }
            ),
            200,
        )

    return (
        jsonify(
            {
                "has_token": True,
                "aid_token": token.aid_token,
                "token_status": token.token_status,
                "center_id": center.id,
                "center_name": center.aid_center_name,
                "token_issued_at": (
                    token.token_issued_at.isoformat() if token.token_issued_at else None
                ),
                "expiry_time": (
                    center.expiry_time.isoformat() if center.expiry_time else None
                ),
            }
        ),
        200,
    )
