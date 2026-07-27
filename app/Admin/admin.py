import uuid
from flask import redirect, url_for, session
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from app import db
from app.models import (Users,Household,DistributionCenter,AidTokens,AuditLog,)
from app.Admin.security import get_current_admin
from app.Admin.dashboard import get_dashboard_data
from app.Admin.audit import log_action


class SecureAdminIndexView(AdminIndexView):

    def is_accessible(self):
        return get_current_admin() is not None

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("admin_auth.login"))

    @expose("/")
    def index(self):
        dashboard = get_dashboard_data()
        return self.render("admin/dashboard_home.html", **dashboard)


# Beneficiaries
class BeneficiaryModelView(ModelView):
    can_create = False
    can_edit = True
    can_delete = False

    column_list = [
        "id",
        "first_name",
        "second_name",
        "national_id",
        "contact",
        "email",
        "user_type",
        "is_active",
        "time_stamp",
    ]

    form_excluded_columns = [
        "current_jti",
        "password",
    ]

    def get_query(self):
        return self.session.query(self.model).filter_by(role="beneficiary")

    def get_count_query(self):
        return self.session.query(db.func.count(self.model.id)).filter_by(
            role="beneficiary"
        )


from werkzeug.security import generate_password_hash

# Aid Workers
class AidWorkerModelView(ModelView):
    can_create = True
    can_edit = True
    can_delete = False

    column_list = [
        "id",
        "first_name",
        "second_name",
        "national_id",
        "contact",
        "email",
        "assigned_center",
        "is_active",
        "time_stamp",
    ]

    form_columns = [
        "first_name",
        "second_name",
        "national_id",
        "contact",
        "email",
        "password",
        "assigned_center",
        "is_active",
    ]

    column_labels = {
        "assigned_center": "Assigned Distribution Center",
        "is_active": "Active Status",
        "time_stamp": "Created At",
    }

    def get_query(self):
        return self.session.query(self.model).filter(
            self.model.role.in_(["aid_worker", "admin"])
        )

    def get_count_query(self):
        return self.session.query(db.func.count(self.model.id)).filter(
            self.model.role.in_(["aid_worker", "admin"])
        )

    def on_model_change(self, form, model, is_created):
        """
        Automatically runs when an admin creates or updates an Aid Worker 
        via the Flask-Admin interface.
        """
        # 1. Force the role to 'aid_worker' if it's a new entry (or ensure it's protected)
        if is_created:
            model.role = "aid_worker"
            model.user_type = "smartphone" # Optional, depending on your user setup
            model.requires_password_change = True

        # 2. Hash the password if a new password was provided in the form
        if form.password.data:
            model.password = generate_password_hash(form.password.data)

        # 3. Log the action to your audit logs
        admin_id = session.get("admin_id")
        if is_created:
            log_action(
                admin_id,
                "Aid Worker Created (Admin Panel)",
                f"{model.first_name} {model.second_name} was created via Flask-Admin."
            )
        else:
            log_action(
                admin_id,
                "Aid Worker Updated (Admin Panel)",
                f"{model.first_name} {model.second_name} was updated via Flask-Admin."
            )

   
        

# Distribution Centers
class DistributionCenterModelView(ModelView):
    can_create = True
    can_edit = True
    can_delete = False

    form_columns = [
        "aid_center_name",
        "start_time",
        "expiry_time",
        "is_active",
    ]

    column_formatters = {
        "workers": lambda v, c, m, p: ", ".join(
            [
                f"{w.first_name} {w.second_name}"
                for w in m.workers
                if w.role in ["aid_worker", "admin"]
            ]
        )
    }

    column_list = [
        "id",
        "aid_center_name",
        "start_time",
        "expiry_time",
        "is_active",
        "current_session_id",
        "workers",
    ]

    column_labels = {
        "aid_center_name": "Center Name",
        "current_session_id": "Session ID",
        "workers": "Assigned Aid Workers",
    }

    def on_model_change(self, form, model, is_created):
        if model.is_active and not model.current_session_id:
            model.current_session_id = str(uuid.uuid4())
        elif not model.is_active:
            model.current_session_id = None

        if is_created:
            log_action(
                session.get("admin_id"),
                "Distribution Center Created",
                f"{model.aid_center_name} was created.",
            )
        else:
            log_action(
                session.get("admin_id"),
                "Distribution Center Updated",
                f"{model.aid_center_name} was updated.",
            )

    def on_model_delete(self, model):
        log_action(
            session.get("admin_id"),
            "Distribution Center Deleted",
            f"{model.aid_center_name} was deleted.",
        )


# Aid Tokens
class AidTokenModelView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False

    column_list = [
        "id",
        "aid_token",
        "user_id",
        "token_status",
        "token_issued_at",
        "distribution_center_id",
        "session_id",
    ]

    column_labels = {
        "aid_token": "Token Code",
        "user_id": "Assigned User ID",
        "distribution_center_id": "Center ID",
    }


# Households
class HouseholdModelView(ModelView):
    can_create = False
    can_edit = True
    can_delete = False

    column_list = [
        "id",
        "user_id",
        "center_id",
        "total_members",
        "dependents_count",
        "disability_present",
        "income_level",
        "is_profile_complete",
        "vulnerability_score",
    ]


# Audit Logs
class AuditLogModelView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False

    column_list = ["id", "user_id", "action", "details", "timestamp"]


# Initialize Admin
def init_admin(app):
    admin = Admin(
        app,
        name="AidBridge HQ",
        url="/admin",
        index_view=SecureAdminIndexView(name="Dashboard"),
    )

    admin.add_view(
        BeneficiaryModelView(
            Users,
            db.session,
            name="Beneficiaries",
            endpoint="beneficiaries",
            category="Users",
        )
    )

    admin.add_view(
        AidWorkerModelView(
            Users,
            db.session,
            name="Aid Workers",
            endpoint="aid_workers",
            category="Users",
        )
    )

    admin.add_view(
        DistributionCenterModelView(
            DistributionCenter,
            db.session,
            name="Distribution Centers",
            category="Distribution",
        )
    )

    admin.add_view(
        AidTokenModelView(
            AidTokens,
            db.session,
            name="Aid Tokens",
            category="Distribution",
        )
    )

    admin.add_view(
        HouseholdModelView(
            Household,
            db.session,
            name="Households",
            category="Distribution",
        )
    )

    admin.add_view(
        AuditLogModelView(
            AuditLog,
            db.session,
            name="Audit Logs",
            category="Monitoring",
        )
    )
