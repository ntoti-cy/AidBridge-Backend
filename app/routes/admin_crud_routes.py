from flask import Blueprint, request, jsonify, session
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from app import db
from app.models import AidTokens, Users, Household, DistributionCenter
from app.Admin.audit import log_action
from app.utilis.sessions import auto_expire_session
from app.utilis.timezone import make_eat

admin_bp = Blueprint("admin_bp", __name__)


def get_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    admin = db.session.get(Users, admin_id)
    if not admin or admin.role != "admin":
        return None
    return admin

def validate_worker(data, worker=None):
    errors = {}
    if not data:
        return {"general": ["Invalid Request Body"]}

    for key, value in data.items():
        if isinstance(value, str):
            data[key] = value.strip()

    if worker is None:
        required_fields = ["first_name", "second_name", "national_id", "contact", "email", "password"]
        for field in required_fields:
            if not data.get(field):
                errors.setdefault(field, []).append(
                    f"{field.replace('_', ' ').title()} is required."
                )

    if "first_name" in data:
        first_name = data.get("first_name")
        if not first_name or not str(first_name).strip():
            errors.setdefault("first_name", []).append("First name is required.")
        elif not str(first_name).strip().isalpha():
            errors.setdefault("first_name", []).append("First name must contain only letters.")

    if "second_name" in data:
        second_name = data.get("second_name")
        if not second_name or not str(second_name).strip():
            errors.setdefault("second_name", []).append("Second name is required.")
        elif not str(second_name).strip().isalpha():
            errors.setdefault("second_name", []).append("Second name must contain only letters.")

    if "national_id" in data:
        national_id = data.get("national_id")
        if not national_id:
            errors.setdefault("national_id", []).append("National ID is required.")
        else:
            national_id_str = str(national_id).strip()
            if not national_id_str.isdigit():
                errors.setdefault("national_id", []).append("National ID must contain only numbers.")
            else:
                existing = Users.query.filter_by(national_id=national_id_str).first()
                if existing and (worker is None or existing.id != worker.id):
                    errors.setdefault("national_id", []).append("National ID already exists.")

    if "contact" in data:
        contact = data.get("contact")
        if not contact:
            errors.setdefault("contact", []).append("Contact is required.")
        else:
            contact_str = str(contact).strip()
            if not contact_str.isdigit():
                errors.setdefault("contact", []).append("Contact must contain only numbers.")
            elif len(contact_str) < 10:
                errors.setdefault("contact", []).append("Contact must be at least 10 digits.")
            else:
                existing = Users.query.filter_by(contact=contact_str).first()
                if existing and (worker is None or existing.id != worker.id):
                    errors.setdefault("contact", []).append("Contact already exists.")

    if "email" in data:
        email = data.get("email")
        if not email:
            errors.setdefault("email", []).append("Email is required.")
        else:
            email_str = str(email).strip().lower()
            if "@" not in email_str or "." not in email_str:
                errors.setdefault("email", []).append("Invalid email address.")
            else:
                existing = Users.query.filter_by(email=email_str).first()
                if existing and (worker is None or existing.id != worker.id):
                    errors.setdefault("email", []).append("Email already exists.")

    if "password" in data and data.get("password"):
        password = data.get("password")
        if len(password) < 6:
            errors.setdefault("password", []).append("Password must be at least 6 characters.")

    return errors

@admin_bp.route("/aid-workers", methods=["POST"])
def create_aid_worker():
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    errors = validate_worker(data)
    if errors:
        return jsonify({"errors": errors}), 400

    center_id = data.get("assigned_center_id") or data.get("assigned_center")
    if center_id:
        center = db.session.get(DistributionCenter, center_id)
        if not center:
            return jsonify({"error": "Distribution Center not found"}), 404

        existing_officer = Users.query.filter(
            Users.assigned_center_id == center.id,
            Users.role == "aid_worker",
        ).first()

        if existing_officer:
            return (
                jsonify(
                    {
                        "error": (
                            f"'{center.aid_center_name}' is already assigned to "
                            f"{existing_officer.first_name} {existing_officer.second_name}. "
                            "A distribution center can only have 1 worker at a time."
                        )
                    }
                ),
                409,
            )
    else:
        center_id = None

    hashed_password = generate_password_hash(data["password"])
    worker = Users(
        first_name=data["first_name"].strip().title(),
        second_name=data["second_name"].strip().title(),
        national_id=data["national_id"].strip(),
        contact=data["contact"].strip(),
        email=data["email"].strip().lower(),
        password=hashed_password,
        role="aid_worker",
        user_type="smartphone",
        requires_password_change=True,
        is_active=True,
        assigned_center_id=center_id,
    )

    try:
        db.session.add(worker)
        db.session.commit()
        log_action(
            admin.id,
            "Aid Worker Created",
            f"{worker.first_name} {worker.second_name} created successfully.",
        )
        return (
            jsonify(
                {
                    "message": "Aid Worker created successfully.",
                    "worker": {
                        "id": worker.id,
                        "first_name": worker.first_name,
                        "second_name": worker.second_name,
                        "email": worker.email,
                        "contact": worker.contact,
                        "is_active": worker.is_active,
                        "assigned_center_id": worker.assigned_center_id,
                    },
                }
            ),
            201,
        )
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Worker already exists."}), 409
    except Exception as e:
        db.session.rollback()
        return (
            jsonify({"error": "Failed to create Aid Worker.", "details": str(e)}),
            500,
        )


@admin_bp.route("/aid-workers", methods=["GET"])
def get_aid_workers():
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    workers = Users.query.filter_by(role="aid_worker").order_by(Users.first_name.asc()).all()
    data = []
    for worker in workers:
        center = None
        if worker.assigned_center_id:
            center = db.session.get(DistributionCenter, worker.assigned_center_id)
        data.append(
            {
                "id": worker.id,
                "first_name": worker.first_name,
                "second_name": worker.second_name,
                "national_id": worker.national_id,
                "contact": worker.contact,
                "email": worker.email,
                "is_active": worker.is_active,
                "assigned_center_id": worker.assigned_center_id,
                "assigned_center": (center.aid_center_name if center else None),
                "requires_password_change": worker.requires_password_change,
            }
        )
    return jsonify({"count": len(data), "workers": data}), 200


@admin_bp.route("/aid-workers/<int:worker_id>", methods=["GET"])
def get_aid_worker(worker_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    worker = db.session.get(Users, worker_id)
    if not worker or worker.role != "aid_worker":
        return jsonify({"error": "Aid Worker not found"}), 404

    center = None
    if worker.assigned_center_id:
        center = db.session.get(DistributionCenter, worker.assigned_center_id)

    return (
        jsonify(
            {
                "worker": {
                    "id": worker.id,
                    "first_name": worker.first_name,
                    "second_name": worker.second_name,
                    "national_id": worker.national_id,
                    "contact": worker.contact,
                    "email": worker.email,
                    "role": worker.role,
                    "user_type": worker.user_type,
                    "is_active": worker.is_active,
                    "requires_password_change": worker.requires_password_change,
                    "assigned_center_id": worker.assigned_center_id,
                    "assigned_center": (center.aid_center_name if center else None),
                }
            }
        ),
        200,
    )


@admin_bp.route("/aid-workers/<int:worker_id>", methods=["PUT"])
def update_worker(worker_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    worker = db.session.get(Users, worker_id)
    if not worker or worker.role != "aid_worker":
        return jsonify({"error": "Aid Worker not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request body"}), 400

    errors = validate_worker(data, worker)
    if errors:
        return jsonify({"errors": errors}), 400

    old_center_id = worker.assigned_center_id

    try:
        if "first_name" in data and data["first_name"]:
            worker.first_name = data["first_name"].strip().title()
        if "second_name" in data and data["second_name"]:
            worker.second_name = data["second_name"].strip().title()
        if "national_id" in data and data["national_id"]:
            worker.national_id = str(data["national_id"]).strip()
        if "contact" in data and data["contact"]:
            worker.contact = str(data["contact"]).strip()
        if "email" in data and data["email"]:
            worker.email = data["email"].strip().lower()
        if data.get("password"):
            worker.password = generate_password_hash(data["password"])

        if "assigned_center_id" in data or "assigned_center" in data:
            center_id = (
                data.get("assigned_center_id")
                if "assigned_center_id" in data
                else data.get("assigned_center")
            )

            if center_id is None:
                worker.assigned_center_id = None
            else:
                center = db.session.get(DistributionCenter, center_id)
                if not center:
                    return jsonify({"error": "Distribution Center not found"}), 404

                existing_officer = Users.query.filter(
                    Users.assigned_center_id == center.id,
                    Users.role == "aid_worker",
                    Users.id != worker.id,
                ).first()

                if existing_officer:
                    return (
                        jsonify(
                            {
                                "error": (
                                    f"'{center.aid_center_name}' is already assigned to "
                                    f"{existing_officer.first_name} {existing_officer.second_name}. "
                                    "A distribution center can only have 1 worker at a time."
                                )
                            }
                        ),
                        409,
                    )

                worker.assigned_center_id = center.id

        db.session.commit()

        if old_center_id != worker.assigned_center_id:
            old_name = "None"
            if old_center_id:
                old_center = db.session.get(DistributionCenter, old_center_id)
                if old_center:
                    old_name = old_center.aid_center_name

            new_name = "None"
            if worker.assigned_center_id:
                new_center = db.session.get(DistributionCenter, worker.assigned_center_id)
                if new_center:
                    new_name = new_center.aid_center_name

            log_action(
                admin.id,
                "Aid Worker Reassigned",
                f"{worker.first_name} {worker.second_name} reassigned from {old_name} to {new_name}.",
            )

        log_action(
            admin.id,
            "Aid Worker Updated",
            f"{worker.first_name} {worker.second_name} updated.",
        )

        return (
            jsonify(
                {
                    "message": "Aid Worker updated successfully.",
                    "worker": {
                        "id": worker.id,
                        "first_name": worker.first_name,
                        "second_name": worker.second_name,
                        "national_id": worker.national_id,
                        "contact": worker.contact,
                        "email": worker.email,
                        "assigned_center_id": worker.assigned_center_id,
                        "is_active": worker.is_active,
                    },
                }
            ),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update Aid Worker.", "details": str(e)}), 500


@admin_bp.route("/aid-workers/<int:worker_id>/activate", methods=["PATCH"])
def activate_worker(worker_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    worker = db.session.get(Users, worker_id)
    if not worker or worker.role != "aid_worker":
        return jsonify({"error": "Aid Worker not found"}), 404

    if worker.is_active:
        return jsonify({"message": "Aid Worker is already active."}), 200

    try:
        worker.is_active = True
        db.session.commit()
        log_action(
            admin.id,
            "Aid Worker Activated",
            f"{worker.first_name} {worker.second_name} was activated.",
        )
        return (
            jsonify(
                {
                    "message": "Aid Worker activated successfully.",
                    "worker": {"id": worker.id, "is_active": worker.is_active},
                }
            ),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to activate Aid Worker.", "details": str(e)}), 500


@admin_bp.route("/aid-workers/<int:worker_id>/deactivate", methods=["PATCH"])
def deactivate_worker(worker_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    worker = db.session.get(Users, worker_id)
    if not worker or worker.role != "aid_worker":
        return jsonify({"error": "Aid Worker not found"}), 404

    if not worker.is_active:
        return jsonify({"message": "Aid Worker is already inactive."}), 200

    try:
        vacated_center = None
        if worker.assigned_center_id:
            vacated_center = db.session.get(DistributionCenter, worker.assigned_center_id)

        worker.is_active = False
        worker.assigned_center_id = None
        db.session.commit()

        log_action(
            admin.id,
            "Aid Worker Deactivated",
            f"{worker.first_name} {worker.second_name} was deactivated.",
        )

        if vacated_center:
            log_action(
                admin.id,
                "Distribution Center Unassigned",
                f"{vacated_center.aid_center_name} was automatically unassigned "
                f"because {worker.first_name} {worker.second_name} was deactivated.",
            )

        return (
            jsonify(
                {
                    "message": "Aid Worker deactivated successfully.",
                    "worker": {
                        "id": worker.id,
                        "is_active": worker.is_active,
                        "assigned_center_id": worker.assigned_center_id,
                    },
                }
            ),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to deactivate Aid Worker.", "details": str(e)}), 500


@admin_bp.route("/distribution-centers", methods=["POST"])
def create_distribution_center():
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": {"general": ["Invalid request body"]}}), 400

    errors = {}
    aid_center_name = data.get("aid_center_name")
    if not aid_center_name:
        errors.setdefault("aid_center_name", []).append("Aid Center Name is required.")
    else:
        existing = DistributionCenter.query.filter_by(aid_center_name=aid_center_name).first()
        if existing:
            errors.setdefault("aid_center_name", []).append("Distribution Center already exists.")

    if errors:
        return jsonify({"error": errors}), 400

    start_time = data.get("start_time")
    expiry_time = data.get("expiry_time")
    
    if start_time and isinstance(start_time, str):
        try:
            start_time = make_eat(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass
            
    if expiry_time and isinstance(expiry_time, str):
        try:
            expiry_time = make_eat(datetime.strptime(expiry_time, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass

    center = DistributionCenter(
        aid_center_name=aid_center_name,
        start_time=start_time,
        expiry_time=expiry_time,
    )

    db.session.add(center)
    db.session.commit()

    log_action(
        admin.id,
        "Distribution Center Created",
        f"{center.aid_center_name} was created.",
    )

    return jsonify({"message": "Distribution Center created successfully.", "center_id": center.id}), 201


@admin_bp.route("/distribution-centers", methods=["GET"])
def get_distribution_centers():
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    centers = DistributionCenter.query.order_by(DistributionCenter.aid_center_name).all()
    results = []
    for center in centers:
        officer = Users.query.filter_by(assigned_center_id=center.id, role="aid_worker").first()
        households_count = Household.query.filter_by(center_id=center.id).count()
        results.append(
            {
                "id": center.id,
                "aid_center_name": center.aid_center_name,
                "is_active": center.is_active,
                "officer": (
                    {
                        "id": officer.id,
                        "first_name": officer.first_name,
                        "second_name": officer.second_name,
                    }
                    if officer
                    else None
                ),
                "households": households_count,
            }
        )
    return jsonify(results), 200


@admin_bp.route("/distribution-centers/<int:center_id>", methods=["GET"])
def get_distribution_center(center_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    center = DistributionCenter.query.get(center_id)
    if not center:
        return jsonify({"error": "Distribution Center not found."}), 404

    auto_expire_session(center)

    officer = Users.query.filter_by(assigned_center_id=center.id, role="aid_worker").first()
    households_count = Household.query.filter_by(center_id=center.id).count()

    return (
        jsonify(
            {
                "id": center.id,
                "aid_center_name": center.aid_center_name,
                "is_active": center.is_active,
                "households": households_count,
                "officer": (
                    {
                        "id": officer.id,
                        "first_name": officer.first_name,
                        "second_name": officer.second_name,
                        "contact": officer.contact,
                        "email": officer.email,
                        "is_active": officer.is_active,
                    }
                    if officer
                    else None
                ),
            }
        ),
        200,
    )


@admin_bp.route("/distribution-centers/<int:center_id>/activate", methods=["PATCH"])
def activate_distribution_center(center_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    center = DistributionCenter.query.get(center_id)
    if not center:
        return jsonify({"error": "Distribution Center not found."}), 404

    auto_expire_session(center)

    if center.is_active:
        return jsonify({"message": "Distribution Center is already active."}), 200

    center.is_active = True
    db.session.commit()

    log_action(
        admin.id,
        "Distribution Center Activated",
        f"{center.aid_center_name} was activated.",
    )

    return (
        jsonify(
            {
                "message": "Distribution Center activated successfully.",
                "center": {
                    "id": center.id,
                    "aid_center_name": center.aid_center_name,
                    "is_active": center.is_active,
                },
            }
        ),
        200,
    )


@admin_bp.route("/distribution-centers/<int:center_id>/deactivate", methods=["PATCH"])
def deactivate_distribution_center(center_id):
    admin = get_admin()
    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    center = DistributionCenter.query.get(center_id)
    if not center:
        return jsonify({"error": "Distribution Center not found."}), 404

    if not center.is_active:
        return jsonify({"message": "Distribution Center is already inactive."}), 200

    try:
        AidTokens.query.filter_by(
            distribution_center_id=center.id,
            session_id=center.current_session_id,
            token_status="active",
        ).update({"token_status": "expired"})

        center.is_active = False
        db.session.commit()

        log_action(
            admin.id,
            "Distribution Center Force Deactivated",
            f"Admin force-deactivated {center.aid_center_name} and expired active tokens.",
        )

        return (
            jsonify(
                {
                    "message": "Distribution Center deactivated successfully and active tokens expired.",
                    "center": {
                        "id": center.id,
                        "aid_center_name": center.aid_center_name,
                        "is_active": center.is_active,
                    },
                }
            ),
            200,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to deactivate Distribution Center.", "details": str(e)}), 500