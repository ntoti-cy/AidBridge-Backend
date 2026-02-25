from functools import wraps
from flask import request, jsonify, current_app
import jwt
from app.models import Users
from app.models import TokenBlocklist
from datetime import datetime
import uuid
from app import db  



#Protected routes token
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = request.headers.get('Authorization')  # Get authorization header from the request (HTTP)

        # Check if the header exists and has the Bearer token
        if auth_token and " " in auth_token:
            token = auth_token.split(" ")[1]  # Extract the token part
        else:
            token = None

        if not token:
            return jsonify({'error': 'Token is missing'}), 401

        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            jti_ = data.get('jti')
            current_user_id = data['user_id']

            if TokenBlocklist.query.filter_by(jti=jti_).first():
             return jsonify({'error': 'Token has been Revoked'}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        return f(current_user_id, *args, **kwargs)

    return decorated


#AidBridge tokens 
def generate_aid_token(user: Users):
    return str(uuid.uuid4()).replace("-", "").upper()[:10]
   
