from app import db
from app.models import AuditLog


def log_action(user_id, action, details=None):
    
    try:
        log = AuditLog(
            user_id=user_id,
            action=action,
            details=details,
        )

        db.session.add(log)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"Audit Log Error: {e}")