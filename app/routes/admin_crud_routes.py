from flask import Blueprint, request, jsonify, session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from app import db
from app.models import AidTokens, Users, Household, DistributionCenter
from app.Admin.audit import log_action

admin_bp = Blueprint("admin_bp", __name__)


def get_admin():
    """
    Returns the currently logged-in admin.
    """

    admin_id = session.get("admin_id")

    if not admin_id:
        return None

    admin = db.session.get(Users, admin_id)

    if not admin:
        return None

    if admin.role != "admin":
        return None

    return admin


def validate_worker(data, worker=None):
    """
    Validates Aid Worker data aligned with auth route validation.
    worker=None -> Create
    worker=Users object -> Update
    """
    errors = {}

    if not data:
        return {"general": ["Invalid Request Body"]}

    for key, value in data.items():
        if isinstance(value, str):
            data[key] = value.strip()

    required_fields = [
        "first_name",
        "second_name",
        "national_id",
        "contact",
        "email",
    ]

    if worker is None:
        required_fields.append("password")

    for field in required_fields:
        if not data.get(field):
            errors.setdefault(field, []).append(
                f"{field.replace('_', ' ').title()} is required."
            )

    first_name = data.get("first_name")
    if first_name and not first_name.isalpha():
        errors.setdefault("first_name", []).append(
            "First name must contain only letters."
        )

    second_name = data.get("second_name")
    if second_name and not second_name.isalpha():
        errors.setdefault("second_name", []).append(
            "Second name must contain only letters."
        )

    national_id = data.get("national_id")
    if national_id:
        national_id_str = str(national_id)
        if not national_id_str.isdigit():
            errors.setdefault("national_id", []).append(
                "National ID must contain only numbers."
            )
        else:
            existing = Users.query.filter_by(national_id=national_id_str).first()
            if existing and (worker is None or existing.id != worker.id):
                errors.setdefault("national_id", []).append(
                    "National ID already exists."
                )

    contact = data.get("contact")
    if contact:
        contact_str = str(contact)
        if not contact_str.isdigit():
            errors.setdefault("contact", []).append(
                "Contact must contain only numbers."
            )
        elif len(contact_str) < 10:
            errors.setdefault("contact", []).append(
                "Contact must be at least 10 digits."
            )
        else:
            existing = Users.query.filter_by(contact=contact_str).first()
            if existing and (worker is None or existing.id != worker.id):
                errors.setdefault("contact", []).append("Contact already exists.")

    email = data.get("email")
    if email:
        if "@" not in email or "." not in email:
            errors.setdefault("email", []).append("Invalid email address.")
        else:
            existing = Users.query.filter_by(email=email.lower()).first()
            if existing and (worker is None or existing.id != worker.id):
                errors.setdefault("email", []).append("Email already exists.")

    password = data.get("password")
    if worker is None and password and len(password) < 6:
        errors.setdefault("password", []).append(
            "Password must be at least 6 characters."
        )

    return errors


# Create Aid Worker
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
            jsonify(
                {
                    "error": "Failed to create Aid Worker.",
                    "details": str(e),
                }
            ),
            500,
        )


# Get All Aid Workers
@admin_bp.route("/aid-workers", methods=["GET"])
def get_aid_workers():

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    workers = (
        Users.query.filter_by(role="aid_worker").order_by(Users.first_name.asc()).all()
    )

    data = []

    for worker in workers:

        center = None

        if worker.assigned_center_id:
            center = db.session.get(
                DistributionCenter,
                worker.assigned_center_id,
            )

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

    return (
        jsonify(
            {
                "count": len(data),
                "workers": data,
            }
        ),
        200,
    )


# Get Single Aid Worker
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
        center = db.session.get(
            DistributionCenter,
            worker.assigned_center_id,
        )

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


# Update Aid Worker
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

        # Update worker information
        worker.first_name = data["first_name"].strip().title()
        worker.second_name = data["second_name"].strip().title()
        worker.national_id = data["national_id"].strip()
        worker.contact = data["contact"].strip()
        worker.email = data["email"].strip().lower()

        # Optional password update
        if data.get("password"):
            worker.password = generate_password_hash(data["password"])

        # Optional center reassignment
        if "assigned_center_id" in data:

            center_id = data.get("assigned_center_id")

            if center_id is None:
                worker.assigned_center_id = None

            else:

                center = db.session.get(
                    DistributionCenter,
                    center_id,
                )

                if not center:
                    return jsonify({"error": "Distribution Center not found"}), 404

                worker.assigned_center_id = center.id

        db.session.commit()

        # Audit Log
        if old_center_id != worker.assigned_center_id:

            old_name = "None"

            if old_center_id:
                old_center = db.session.get(
                    DistributionCenter,
                    old_center_id,
                )

                if old_center:
                    old_name = old_center.aid_center_name

            new_name = "None"

            if worker.assigned_center_id:
                new_center = db.session.get(
                    DistributionCenter,
                    worker.assigned_center_id,
                )

                if new_center:
                    new_name = new_center.aid_center_name

            log_action(
                admin.id,
                "Aid Worker Reassigned",
                f"{worker.first_name} {worker.second_name} "
                f"reassigned from {old_name} to {new_name}.",
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

        return (
            jsonify(
                {
                    "error": "Failed to update Aid Worker.",
                    "details": str(e),
                }
            ),
            500,
        )


# Delete Aid Worker
@admin_bp.route("/aid-workers/<int:worker_id>", methods=["DELETE"])
def delete_worker(worker_id):

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    worker = db.session.get(Users, worker_id)

    if not worker or worker.role != "aid_worker":
        return jsonify({"error": "Aid Worker not found"}), 404

    # Prevent deleting an assigned worker
    if worker.assigned_center_id:

        center = db.session.get(
            DistributionCenter,
            worker.assigned_center_id,
        )

        return (
            jsonify(
                {
                    "error": (
                        f"Worker is assigned to "
                        f"{center.aid_center_name}. "
                        "Reassign or unassign the worker before deleting."
                    )
                }
            ),
            400,
        )

    worker_name = f"{worker.first_name} {worker.second_name}"

    try:

        db.session.delete(worker)
        db.session.commit()

        log_action(
            admin.id,
            "Aid Worker Deleted",
            f"{worker_name} was deleted.",
        )

        return (
            jsonify({"message": "Aid Worker deleted successfully."}),
            200,
        )

    except Exception as e:

        db.session.rollback()

        return (
            jsonify(
                {
                    "error": "Failed to delete Aid Worker.",
                    "details": str(e),
                }
            ),
            500,
        )


# Activate Aid Worker
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

        return (
            jsonify({"error": "Failed to activate Aid Worker.", "details": str(e)}),
            500,
        )


# Deactivate Aid Worker
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

        worker.is_active = False

        db.session.commit()

        log_action(
            admin.id,
            "Aid Worker Deactivated",
            f"{worker.first_name} {worker.second_name} was deactivated.",
        )

        return (
            jsonify(
                {
                    "message": "Aid Worker deactivated successfully.",
                    "worker": {"id": worker.id, "is_active": worker.is_active},
                }
            ),
            200,
        )

    except Exception as e:

        db.session.rollback()

        return (
            jsonify({"error": "Failed to deactivate Aid Worker.", "details": str(e)}),
            500,
        )


# Create Distribution Center
@admin_bp.route("/distribution-centers", methods=["POST"])
def create_distribution_center():

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()

    if not data:
        return jsonify({"error": {"general": ["Invalid request body"]}}), 400

    errors = {}

    required_fields = [
        "aid_center_name",
        "county",
        "sub_county",
        "location",
    ]

    for field in required_fields:
        if not data.get(field):
            errors.setdefault(field, []).append(
                f"{field.replace('_', ' ').title()} is required."
            )

    aid_center_name = data.get("aid_center_name")
    start_time = data.get("start_time")
    expiry_time = data.get("expiry_time")

    # Check duplicate center name
    if aid_center_name:
        existing = DistributionCenter.query.filter_by(
            aid_center_name=aid_center_name
        ).first()

        if existing:
            errors.setdefault("aid_center_name", []).append(
                "Distribution Center already exists."
            )

    if errors:
        return jsonify({"error": errors}), 400

    center = DistributionCenter(
        aid_center_name=aid_center_name,
        start_time=start_time,
        expiry_time=expiry_time,
        is_active=True,
    )

    db.session.add(center)
    db.session.commit()

    log_action(
        admin.id,
        "Distribution Center Created",
        f"{center.aid_center_name} was created.",
    )

    return (
        jsonify(
            {
                "message": "Distribution Center created successfully.",
                "center_id": center.id,
            }
        ),
        201,
    )


# Get All Distribution Centers
@admin_bp.route("/distribution-centers", methods=["GET"])
def get_distribution_centers():

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    centers = DistributionCenter.query.order_by(
        DistributionCenter.aid_center_name
    ).all()

    results = []

    for center in centers:

        workers_count = Users.query.filter_by(
            assigned_center_id=center.id, role="aid_worker"
        ).count()

        households_count = Household.query.filter_by(center_id=center.id).count()

        results.append(
            {
                "id": center.id,
                "aid_center_name": center.aid_center_name,
                "county": center.county,
                "sub_county": center.sub_county,
                "location": center.location,
                "is_active": center.is_active,
                "workers_assigned": workers_count,
                "households": households_count,
            }
        )

    return jsonify(results), 200


# Get One Distribution Center
@admin_bp.route("/distribution-centers/<int:center_id>", methods=["GET"])
def get_distribution_center(center_id):

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    center = DistributionCenter.query.get(center_id)

    if not center:
        return jsonify({"error": "Distribution Center not found."}), 404

    workers = Users.query.filter_by(
        assigned_center_id=center.id, role="aid_worker"
    ).all()

    households_count = Household.query.filter_by(center_id=center.id).count()

    worker_list = []

    for worker in workers:
        worker_list.append(
            {
                "id": worker.id,
                "first_name": worker.first_name,
                "second_name": worker.second_name,
                "contact": worker.contact,
                "email": worker.email,
                "is_active": worker.is_active,
            }
        )

    return (
        jsonify(
            {
                "id": center.id,
                "aid_center_name": center.aid_center_name,
                "county": center.county,
                "sub_county": center.sub_county,
                "location": center.location,
                "is_active": center.is_active,
                "workers_assigned": len(worker_list),
                "households": households_count,
                "workers": worker_list,
            }
        ),
        200,
    )


# Activate Distribution Center
@admin_bp.route("/distribution-centers/<int:center_id>/activate", methods=["PATCH"])
def activate_distribution_center(center_id):

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    center = DistributionCenter.query.get(center_id)

    if not center:
        return jsonify({"error": "Distribution Center not found."}), 404

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


# Deactivate Distribution Center
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
        # Admin emergency shutdown: cascade expiration to active tokens
        AidTokens.query.filter_by(
            distribution_center_id=center.id, token_status="active"
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
        return (
            jsonify(
                {
                    "error": "Failed to deactivate Distribution Center.",
                    "details": str(e),
                }
            ),
            500,
        )


# Delete Distribution Center
@admin_bp.route("/distribution-centers/<int:center_id>", methods=["DELETE"])
def delete_distribution_center(center_id):

    admin = get_admin()

    if not admin:
        return jsonify({"error": "Unauthorized"}), 401

    center = DistributionCenter.query.get(center_id)

    if not center:
        return jsonify({"error": "Distribution Center not found."}), 404

    # Safety Check 1: Assigned Aid Workers
    assigned_workers = Users.query.filter_by(
        assigned_center_id=center.id, role="aid_worker"
    ).count()

    if assigned_workers > 0:
        return (
            jsonify(
                {
                    "error": (
                        f"Cannot delete '{center.aid_center_name}'. "
                        f"{assigned_workers} aid worker(s) are still assigned."
                    )
                }
            ),
            409,
        )

    # Safety Check 2: Registered Households
    assigned_households = Household.query.filter_by(center_id=center.id).count()

    if assigned_households > 0:
        return (
            jsonify(
                {
                    "error": (
                        f"Cannot delete '{center.aid_center_name}'. "
                        f"{assigned_households} household(s) are still registered."
                    )
                }
            ),
            409,
        )

    center_name = center.aid_center_name

    db.session.delete(center)
    db.session.commit()

    log_action(admin.id, "Distribution Center Deleted", f"{center_name} was deleted.")

    return jsonify({"message": "Distribution Center deleted successfully."}), 200
