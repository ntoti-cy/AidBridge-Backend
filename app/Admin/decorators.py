from functools import wraps
from flask import request, jsonify, current_app
import jwt
from app.models import Users

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')

        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({'error': {'general': ['Admin authorization required']}}), 403

        token = auth_header.split(" ")[1]

        try:
            decoded = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            user_id = decoded.get('user_id')

            current_user = Users.query.get(user_id)

            if not current_user or current_user.role != 'admin':
                return jsonify({'error': {'general': ['Only admin can perform this action']}}), 403

        except jwt.ExpiredSignatureError:
            return jsonify({'error': {'general': ['Token expired']}}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': {'general': ['Invalid token']}}), 401

        #pass current_user to route
        return f(current_user, *args, **kwargs)

    return decorated