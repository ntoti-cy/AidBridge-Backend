from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from app.Admin.audit import log_action
from app.models import Users

admin_auth = Blueprint("admin_auth", __name__, template_folder="../templates")


@admin_auth.route("/admin/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        user = Users.query.filter_by(email=email, role="admin").first()

        if not user:
            log_action(
                None, "Failed Login Attempt", f"Failed login attempt for email: {email}"
            )

            flash("Invalid email or password", "danger")
            return redirect(url_for("admin_auth.login"))

        if not check_password_hash(user.password, password):
            log_action(
                None,
                "Failed Login Attempt",
                f"Incorrect password attempt for email: {email}",
            )

            flash("Invalid email or password", "danger")
            return redirect(url_for("admin_auth.login"))

        session["admin_id"] = user.id
        session["admin_name"] = user.first_name
        log_action(user.id, "Administrator Login", f"{user.first_name} logged in.")

        return redirect("/admin/")

    return render_template("admin/login.html")


@admin_auth.route("/admin/logout")
def logout():
    admin_id = session.get("admin_id")
    admin_name = session.get("admin_name")

    if admin_id:
        log_action(admin_id, "Administrator Logout", f"{admin_name} logged out.")

    session.clear()

    return redirect(url_for("admin_auth.login"))
