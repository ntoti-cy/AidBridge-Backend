from flask import redirect, url_for, session
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash
from app import db
from app.models import Users, Household, DistributionCenter, AidTokens, AuditLog
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
    

    form_excluded_columns = [
        "current_jti",
    ]

    def get_query(self):
        return self.session.query(self.model).filter_by(role="beneficiary")

    def get_count_query(self):
        return self.session.query(db.func.count(self.model.id)).filter_by(
            role="beneficiary"
        )


# Aid Workers
class AidWorkerModelView(ModelView):
    can_create = True
    can_edit =True
    can_delete = False

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

        # Ensure role remains aid_worker
        model.role = "aid_worker"

        model.user_type = "smartphone"

        if form.assigned_center.data:
            model.assigned_center = form.assigned_center.data
        else:
            model.assigned_center = None

        # Hash password only if it is not already hashed
        if model.password and not model.password.startswith("pbkdf2:"):
            model.password = generate_password_hash(model.password)

        if is_created:

            log_action(
                session.get("admin_id"),
                "Aid Worker Created",
                f"{model.first_name} {model.second_name} was created.",
            )

        else:

            log_action(
                session.get("admin_id"),
                "Aid Worker Updated",
                f"{model.first_name} {model.second_name} was updated.",
            )

    def on_model_delete(self, model):

        log_action(
            session.get("admin_id"),
            "Aid Worker Deleted",
            f"{model.first_name} {model.second_name} was deleted.",
        )


# Distribution Centers
class DistributionCenterModelView(ModelView):
    can_create=True
    can_edit=True
    can_delete=False

    def on_model_change(self, form, model, is_created):

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


# Households
class HouseholdModelView(ModelView):
    can_create = False
    can_edit = True
    can_delete = False


# Audit Logs
class AuditLogModelView(ModelView):

    can_create = False
    can_edit = False
    can_delete = False


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
