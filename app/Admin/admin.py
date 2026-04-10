from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView 
from flask import  abort
from werkzeug.security import check_password_hash, generate_password_hash
import jwt
from app.models import Users, AidTokens, AuditLog
from app import db


# Secure Base View (JWT Protected)
class SecureModelView(ModelView):

    def is_accessible(self):
        return True
        # token = request.headers.get("Authorization")

        # if not token:
        #     return False

        # try:
        #     # Remove "Bearer "
        #     token = token.split(" ")[1]

        #     decoded = jwt.decode(token, "This is the secret-key", algorithms=["HS256"])

        #     # Only allow admins
        #     return decoded.get("role") == "admin"

        # except Exception:
        #     return False

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


    # INTERCEPT AND VALIDATE BEFORE SAVING TO DB
    def on_model_change(self, form, model, is_created):
        
        if model.first_name and not str(model.first_name).replace(" ", "").isalpha():
            raise ValueError("First name must contain only letters.")

        if model.second_name and not str(model.second_name).replace(" ", "").isalpha():
            raise ValueError("Second name must contain only letters.")

        if model.national_id and not str(model.national_id).isdigit():
            raise ValueError("National ID must contain only numbers.")

        if model.contact:
            contact_str = str(model.contact) # Convert to string safely
            if not contact_str.isdigit():
                raise ValueError("Contact must contain only numbers.")
            elif len(contact_str) < 10:
                raise ValueError("Contact number must be at least 10 digits long.")

        if model.email:
            if '@' not in model.email or '.' not in str(model.email):
                raise ValueError("Email must be a valid email address.")
            
        if form.password.data:
            password_str = str(form.password.data)
            if len(password_str) < 6:
                raise ValueError("Password must be at least 6 characters long.")
                
            if not str(model.password).startswith('scrypt') and not str(model.password).startswith('pbkdf2'):
                model.password = generate_password_hash(password_str)



# This looks up the user's name based on their ID
def format_user_name(view, context, model, name):
    if not model.user_id:
        return "System / None"
    
    # Query the database for this specific user
    user = Users.query.get(model.user_id)
    if user:
        return f"{user.first_name} {user.second_name} (User ID: {user.id})"
    return f"Deleted User (ID: {model.user_id})"

#  Tokens
class TokenManagementView(SecureModelView):
    can_create = False
    can_edit = False
    can_delete = True

    column_list= ['id', 'user_id','aid_token', 'token_status', 'token_issued_at']
   
# This uses the custom formatter to show the user's name instead of just their ID
    column_formatters = {'user_id': format_user_name}

    column_searchable_list = ['aid_token', 'token_status']
    column_filters = ['token_status']


#  Audit Logs 
class SecureAuditLogView(SecureModelView):
    can_create = False
    can_edit = False
    can_delete = False

    column_list = ['id', 'user_id', 'action', 'details', 'timestamp']
    column_formatters = {'user_id': format_user_name}
    column_searchable_list = ['action', 'details']
    column_filters = ['action', 'timestamp']


# 1. How the Dashboard looks like 
class DashboardHomeView(AdminIndexView):
    # Temporarily bypassing security just like the tables so you can see it
    def is_accessible(self):
        return True 

    @expose('/')
    def index(self):
        # Calculate some impressive statistics for the examiners to see
        total_beneficiaries = Users.query.filter_by(user_type='smartphone').count() + Users.query.filter_by(user_type='ussd').count()
        total_officers = Users.query.filter_by(role='officer').count()
        
        # If AidTokens has a status, you can count them. (Wrap in try/except just in case the table is empty)
        try:
            active_tokens = AidTokens.query.filter_by(token_status='active').count()
        except:
            active_tokens = 0

        # Pass these numbers to our HTML template
        return self.render(
            'admin/dashboard_home.html', 
            total_beneficiaries=total_beneficiaries,
            total_officers=total_officers,
            active_tokens=active_tokens
        )    


#  Init Function (Updated for latest Flask-Admin)
def init_admin(app):
   # Initialize Admin WITHOUT template_mode or custom templates
    #admin = Admin(app, name="AidBridge HQ", url="/admin")  # ✅ simple default
    admin = Admin(
        app, 
        name="AidBridge HQ", 
        url="/admin", 
        index_view=DashboardHomeView(name='Dashboard Home') # <--- This is the magic line
    )

    # Add your views
    admin.add_view(UserManagementView(Users, db.session, name="Manage Users"))
    admin.add_view(TokenManagementView(AidTokens, db.session, name="Aid Tokens"))
    admin.add_view(SecureAuditLogView(AuditLog, db.session, name="Audit Logs"))