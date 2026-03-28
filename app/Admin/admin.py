from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView 
from flask import request, abort
import jwt

from app.models import Users, AidTokens, AuditLog
from app import db


# Secure Base View (JWT Protected)
class SecureModelView(ModelView):

    def is_accessible(self):
        token = request.headers.get("Authorization")

        if not token:
            return False

        try:
            # Remove "Bearer "
            token = token.split(" ")[1]

            decoded = jwt.decode(token, "This is the secret-key", algorithms=["HS256"])

            # Only allow admins
            return decoded.get("role") == "admin"

        except Exception:
            return False

    def inaccessible_callback(self, name, **kwargs):
        return abort(403)


#  Users
class UserManagementView(SecureModelView):
    can_create = True
    can_edit = True
    can_delete = True

    column_searchable_list = ['first_name', 'national_id', 'contact', 'email']
    column_filters = ['role', 'user_type']

    column_exclude_list = ['password', 'current_jti']


#  Tokens
class TokenManagementView(SecureModelView):
    can_create = True
    can_edit = True
    can_delete = False

    column_searchable_list = ['aid_token', 'token_status']
    column_filters = ['token_status']


#  Audit Logs (IMMUTABLE 🔥)
class SecureAuditLogView(SecureModelView):
    can_create = False
    can_edit = False
    can_delete = False

    column_searchable_list = ['action', 'timestamp']


#  Init Function (Updated for latest Flask-Admin)
def init_admin(app):
   # Initialize Admin WITHOUT template_mode or custom templates
    admin = Admin(app, name="AidBridge HQ", url="/admin")  # ✅ simple default

    # Add your views
    admin.add_view(UserManagementView(Users, db.session, name="Manage Users"))
    admin.add_view(TokenManagementView(AidTokens, db.session, name="Aid Tokens"))
    admin.add_view(SecureAuditLogView(AuditLog, db.session, name="Audit Logs"))