import uuid
from flask import redirect, url_for, session
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash
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
        # Extract form field values into a dictionary to run validation rules
        data = {
            "first_name": form.first_name.data,
            "second_name": form.second_name.data,
            "national_id": form.national_id.data,
            "contact": form.contact.data,
            "email": form.email.data,
            "password": form.password.data if is_created else None,
        }

        errors = {}

        # Field validation checks
        if not data.get("first_name"):
            errors.setdefault("first_name", []).append("First Name is required.")
        elif not data["first_name"].strip().isalpha():
            errors.setdefault("first_name", []).append(
                "First name must contain only letters."
            )

        if not data.get("second_name"):
            errors.setdefault("second_name", []).append("Second Name is required.")
        elif not data["second_name"].strip().isalpha():
            errors.setdefault("second_name", []).append(
                "Second name must contain only letters."
            )

        national_id = data.get("national_id")
        if not national_id:
            errors.setdefault("national_id", []).append("National ID is required.")
        else:
            nid_str = str(national_id).strip()
            if not nid_str.isdigit():
                errors.setdefault("national_id", []).append(
                    "National ID must contain only numbers."
                )
            else:
                existing_nid = Users.query.filter_by(national_id=nid_str).first()
                if existing_nid and (not is_created or existing_nid.id != model.id):
                    errors.setdefault("national_id", []).append(
                        "National ID already exists."
                    )

        contact = data.get("contact")
        if not contact:
            errors.setdefault("contact", []).append("Contact is required.")
        else:
            contact_str = str(contact).strip()
            if not contact_str.isdigit():
                errors.setdefault("contact", []).append(
                    "Contact must contain only numbers."
                )
            elif len(contact_str) < 10:
                errors.setdefault("contact", []).append(
                    "Contact must be at least 10 digits."
                )
            else:
                existing_contact = Users.query.filter_by(contact=contact_str).first()
                if existing_contact and (
                    not is_created or existing_contact.id != model.id
                ):
                    errors.setdefault("contact", []).append("Contact already exists.")

        email = data.get("email")
        if not email:
            errors.setdefault("email", []).append("Email is required.")
        else:
            email_str = email.strip().lower()
            if "@" not in email_str or "." not in email_str:
                errors.setdefault("email", []).append("Invalid email address.")
            else:
                existing_email = Users.query.filter_by(email=email_str).first()
                if existing_email and (not is_created or existing_email.id != model.id):
                    errors.setdefault("email", []).append("Email already exists.")

        if is_created:
            password = data.get("password")
            if not password:
                errors.setdefault("password", []).append("Password is required.")
            elif len(password) < 6:
                errors.setdefault("password", []).append(
                    "Password must be at least 6 characters."
                )

        if errors:
            error_messages = "; ".join(
                [f"{k}: {', '.join(v)}" for k, v in errors.items()]
            )
            raise ValueError(f"Validation Error -> {error_messages}")

        # One-worker-per-center validation check
        selected_center = form.assigned_center.data
        if selected_center:
            existing_worker = Users.query.filter(
                Users.assigned_center_id == selected_center.id,
                Users.role == "aid_worker",
                Users.id != model.id,
            ).first()

            if existing_worker:
                raise ValueError(
                    f"Conflict: '{selected_center.aid_center_name}' is already assigned to "
                    f"{existing_worker.first_name} {existing_worker.second_name}. "
                    "A distribution center can only have 1 worker at a time."
                )
            model.assigned_center = selected_center
        else:
            model.assigned_center = None

        model.role = "aid_worker"
        model.user_type = "smartphone"

        if is_created:
            model.requires_password_change = True

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
