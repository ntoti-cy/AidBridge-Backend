from flask import Blueprint, jsonify,request
from app.models import AidTokens, DistributionCenter, Users, UssdSession
from app import db
from app.tokens import generate_aid_token, profile_required, token_required 
from werkzeug.security import check_password_hash
from flask import current_app
from app.routes.auth_routes import login,register
from datetime import datetime, timedelta
from app.Admin.audit import log_action


user_bp = Blueprint('user_bp',__name__,)

#USSD
@user_bp.route('/callback', methods=['POST'])
def ussd_callback():
    session_id = request.form.get("sessionId")
    contact = request.form.get("phoneNumber")  
    text = request.form.get("text")

    response = ""   #  initialize response



   # HANDLE GLOBAL BACK OPTION
    if text:
     parts = text.split("*")
     if parts[-1] == "0":  
         if len(parts) > 1:
            parts = parts[:-2]
         else:
            parts = []

         text = "*".join(parts) # if last input is 0
        
    parts = text.split("*") if text else []
    

    # MAIN MENU
    if text == "":
        response = "CON Welcome to Aidbridge Aid Access System\n"
        response += "Bridging Aid to the last Mile\n"
        response += "1.Register\n" 
        response += "2.Login\n"
        response += "3.Exit"

    # REGISTER
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
            national_id = int(parts[3])
            password = parts[4]

            # Build payload for /register including contact from USSD
            data = {
                "first_name": first_name,
                "second_name": second_name,
                "national_id": national_id,
                "contact": contact,  # ensure phone number is used
                "password": password,
            }

            # Call your existing register endpoint
            with current_app.test_request_context(
                '/register',
                method='POST',
                json=data
            ):
                register_response = register()
                if register_response[1] != 201:
                    return f"END {register_response[0].json.get('error')}", 200

            response = "END Registration Successful. Please Login."

    # LOGIN
    elif parts[0] == "2":
        if len(parts) == 1:
            response = "CON Enter Password:"

        elif len(parts) == 2:  # User submitted password
            password = parts[1]

            
            user = Users.query.filter_by(contact=contact).first()

            if not user or not check_password_hash(user.password, password):
                return "END Invalid Credentials.", 200

            # Save or update session in DB
            session = UssdSession.query.filter_by(session_id=session_id).first()
            if not session:
                session = UssdSession(session_id=session_id,
                                       user_id=user.id, 
                                       authenticated=True,
                                       last_active=datetime.utcnow())
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

        elif len(parts) == 3:  # User chose menu option
            choice = parts[2]

            # Fetch session from DB
            session = UssdSession.query.filter_by(session_id=session_id).first()
            if not session or not session.authenticated:
                return "END Session expired. Please login again.", 200

            user = Users.query.get(session.user_id)

            if choice == "1":


            #Find active didtribution session
               
                active_center = DistributionCenter.query.filter_by(is_active=True).first()

                if not active_center:
                    return "END No active distribution Center.", 200

                if active_center.expiry_time and active_center.expiry_time < datetime.utcnow():
                    return "END No active distribution Center.", 200

                # Check if user already has token in THIS distribution session
                existing_token = AidTokens.query.filter_by(
                    user_id=user.id,
                    distribution_center_id=active_center.id
                ).filter(AidTokens.token_status.in_(["active", "inactive"])).first()

                if existing_token:
                    if existing_token.token_status == "active":
                        return "END You already have an active token for this session.", 200
                    if existing_token.token_status == "used":
                        return "END You have already used your token for this session.", 200
                    if existing_token.token_status == "expired":
                        return "END Distribution Session Has Ended.", 200
                

                              
                token = generate_aid_token(user)

                new_token = AidTokens (
                    user_id=user.id,
                    aid_token=token,
                    token_status='active',
                    token_issued_at=datetime.utcnow(),
                    distribution_center_id=active_center.id
                )
                db.session.add(new_token)
                db.session.commit()
# Log token issuance in AuditLog
                log_action(user.id, "Token Issued", f"Aid token {token} issued to {user.first_name} {user.second_name}")

                print(f"Send SMS to {user.contact}: Your Aid Token is {token}")
                response = "END Token sent via SMS."

            elif choice == "2":
                active_center = DistributionCenter.query.filter_by(is_active=True).first()

                if not active_center:
                    return "END No active distribution Center.", 200

                if active_center.expiry_time and active_center.expiry_time < datetime.utcnow():
                    # token.token_status = 'expired'
                    # db.session.commit()
                    return "END Distribution session expired. Your token is now expired.", 200

                

                token = AidTokens.query.filter_by(
                    user_id=user.id,
                    distribution_center_id=active_center.id
                ).first()

                if not token:
                    return "END You have not requested a token.", 200

                response = f"END Token: {token.aid_token}\nStatus: {token.token_status}"

                


            elif choice == "9":
                response = "END Thank you for trusting AidBridge."
                # Clear session on exit
                db.session.delete(session)
                db.session.commit()

            else:
                response = "END Invalid choice."

    # EXIT
    elif parts[0] == "9":
        response = "END Thank you for trusting AidBridge."
        # Clear session if exists
        session = UssdSession.query.filter_by(session_id=session_id).first()
        if session:
            db.session.delete(session)
            db.session.commit()

    else:
        response = "END Invalid option."

    return response, 200    
   
   
   
@user_bp.route('/request-token', methods=['POST', 'GET'])
@token_required
@profile_required
def request_smartphone_token(current_user_id):
    # Verify User (Smartphone users)
    user = Users.query.get(current_user_id)
    if not user:
        return jsonify({"error": "Beneficiary not found"}), 404

    #Fraud check
    if check_for_fraud(current_user_id):
        log_action(current_user_id, "Fraudulent Activity Detected", f"Beneficiary {user.first_name} {user.second_name} attempted to request a token within 24 hours of the last request.")
        return jsonify({"error": "Fraudulent activity detected."}), 400

    # Find the active distribution session
    active_center = DistributionCenter.query.filter_by(is_active=True).first()

    if not active_center:
        return jsonify({"error": "No active distribution session at the moment."}), 404

    if active_center.expiry_time and active_center.expiry_time < datetime.utcnow():
        return jsonify({"error": "The active distribution session has expired."}), 400

    # Check if user already has a token for the session
    existing_token = AidTokens.query.filter_by(
        user_id=user.id,
        distribution_center_id=active_center.id
    ).first()

    if existing_token:
        if existing_token.token_status == "active":
            # Return the existing token so Flutter can redraw the QR code
            return jsonify({
                "message": "Retrieved existing active token.",
                "aid_token": existing_token.aid_token,
                "token_status": existing_token.token_status,
                "center_name": active_center.aid_center_name
            }), 200
            
        elif existing_token.token_status == "used":
            return jsonify({"error": "You have already received your aid for this session."}), 400
            
        elif existing_token.token_status == "expired":
            return jsonify({"error": "Your token for this session has expired."}), 400

    # 4. Generate new token if they don't have one
    token_string = generate_aid_token(user)

    new_token = AidTokens(
        user_id=user.id,
        aid_token=token_string,
        token_status='active',
        token_issued_at=datetime.utcnow(),
        distribution_center_id=active_center.id
    )
    db.session.add(new_token)
    db.session.commit()

    # 5. Log the action
    log_action(user.id, "Token Issued", f"Aid token {token_string} issued to smartphone user {user.first_name} {user.second_name}")

    # 6. Send the token data back to Flutter
    return jsonify({
        "message": "Token generated successfully",
        "aid_token": token_string,
        "token_status": "active",
        "center_name": active_center.aid_center_name
    }), 201

@user_bp.route('/token-history', methods=['GET'])
@token_required
def get_token_history(current_user_id):
    # Fetch all tokens requested by this beneficiary, sorted by newest first
    tokens = AidTokens.query.filter_by(user_id=current_user_id).order_by(AidTokens.token_issued_at.desc()).all()

    history_data = []
    for token in tokens:
        # Check the distribution center to get the actual center name
        session = DistributionCenter.query.get(token.distribution_center_id) if token.distribution_center_id else None
        
        history_data.append({
            "id": token.id,
            "aid_token": token.aid_token,
            "token_status": token.token_status,
            "token_issued_at": token.token_issued_at.strftime('%Y-%m-%d %H:%M:%S') if token.token_issued_at else None,
            "center_name": session.aid_center_name if session else "General Distribution"
        })

    return jsonify({
        "message": "Token history retrieved successfully",
        "history": history_data
    }), 200   


def check_for_fraud(user_id):
    #find the most recent token issued to the user
    last_token = AidTokens.query.filter_by(user_id=user_id)\
        .order_by(AidTokens.token_issued_at.desc()).first()
    
    if last_token and last_token.token_issued_at:
        # Check if less than 24 hours have passed
        if datetime.utcnow() - last_token.token_issued_at < timedelta(hours=24):
            return True 
    return False