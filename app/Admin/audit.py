from app.models import AuditLog
from app import db

def log_action(user_id, action, details=None):
    log = AuditLog(
        user_id=user_id,
        action=action,
        details=details
    )
    db.session.add(log)
    db.session.commit()