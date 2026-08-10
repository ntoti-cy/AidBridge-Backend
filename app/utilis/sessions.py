from app import db
from app.models import DistributionCenter, AidTokens
from app.utilis.timezone import now_eat


def auto_expire_session(center):
    if not center:
        return False

    # Nothing to expire
    if not center.is_active:
        return False

    # No expiry configured
    if not center.expiry_time:
        return False

    current_time = now_eat()

    # Make sure both datetimes are timezone-aware
    expiry_time = center.expiry_time

    if expiry_time.tzinfo is None:
        from app.utilis.timezone import make_eat
        expiry_time = make_eat(expiry_time)

    # Session has not expired yet
    if current_time < expiry_time:
        return False

    # Save the session ID before clearing it
    current_session_id = center.current_session_id

    # Expire all unused tokens from this session
    if current_session_id:
        AidTokens.query.filter(
            AidTokens.distribution_center_id == center.id,
            AidTokens.session_id == current_session_id,
            AidTokens.token_status.in_(["pending", "active"]),
        ).update(
            {"token_status": "expired"},
            synchronize_session=False,
        )

    # End the session
    center.is_active = False
    center.start_time = None
    center.expiry_time = None
    center.current_session_id = None

    db.session.commit()

    return True