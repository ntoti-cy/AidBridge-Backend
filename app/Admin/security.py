from flask import session
from app import db
from app.models import Users


def get_current_admin():
    """
    Returns the currently logged in administrator.
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
