from . import db
from datetime import datetime


class Users(db.Model):
    __tablename__ = "Users"
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(150), nullable=False)
    second_name = db.Column(db.String(150), nullable=False)
    national_id = db.Column(db.Integer, unique=True, nullable=False)
    contact = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)

    user_type = db.Column(db.String(50), nullable=False, default="smartphone")
    role = db.Column(db.String(50), nullable=False, default="beneficiary")
    requires_password_change = db.Column(db.Boolean, default=False)
    assigned_center_id = db.Column(db.Integer, db.ForeignKey("distribution_centers.id"), nullable=True)
    assigned_center = db.relationship("DistributionCenter", backref="workers")
    is_active = db.Column(db.Boolean, default=True)

    current_jti = db.Column(db.String(120))  # for JWT tracking
    time_stamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.first_name}>"


class AidTokens(db.Model):
    __tablename__ = "aid_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("Users.id"))
    aid_token = db.Column(db.String(100), unique=True, nullable=False)
    token_status = db.Column(db.String(20), default="inactive")
    token_issued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    distribution_center_id = db.Column(
        db.Integer, db.ForeignKey("distribution_centers.id"), nullable=True
    )
    session_id = db.Column(db.String(36), nullable =True)

    def __repr__(self):
        return f"<AidToken {self.aid_token}>"


class TokenBlocklist(db.Model):
    __tablename__ = "token_blocklist"
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(150), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("Users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Token {self.jti}>"


class UssdSession(db.Model):
    __tablename__ = "ussd_sessions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(150), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("Users.id"))
    authenticated = db.Column(db.Boolean, default=False)
    current_menu = db.Column(db.String(50), default="main")
    profile_step = db.Column(db.Integer, default=0)
    profile_data = db.Column(db.JSON, default=dict )
    last_active = db.Column(db.DateTime, default=datetime.utcnow)


    def __repr__(self):
        return f"<Session {self.session_id}>"


class DistributionCenter(db.Model):
    __tablename__ = "distribution_centers"
    id = db.Column(db.Integer, primary_key=True)
    aid_center_name = db.Column(db.String(150), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_time = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=False)
    current_session_id = db.Column(db.String(36), nullable =True)

    def __repr__(self):
        return self.aid_center_name


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("Users.id"))
    action = db.Column(db.String(200), nullable=False)
    details = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AuditLog {self.action}>"


class Household(db.Model):
    __tablename__ = "households"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("Users.id"), nullable=False, unique=True
    )
    center_id = db.Column(
        db.Integer, db.ForeignKey("distribution_centers.id"), nullable=True
    )

    total_members = db.Column(db.Integer, default=1)
    dependents_count = db.Column(db.Integer, default=0)
    disability_present = db.Column(db.Boolean, default=False)
    income_level = db.Column(db.Float, default=0.0)

    is_profile_complete = db.Column(db.Boolean, default=False)
    vulnerability_score = db.Column(db.Float, default=0.0)

    def calculate_score(self):
        # Weighted Logic
        score = (self.total_members * 1.0) + (self.dependents_count * 1.5)
        if self.disability_present:
            score += 5.0
        self.vulnerability_score = score
        return score
