from app import db
from app.models import AidTokens, DistributionCenter
from app.Admin.audit import log_action
from app.utilis.timezone import now_eat


def auto_expire_session(center: DistributionCenter):
    #end session if the expiry time has passed
    if not center or not center.is_active or not center.expiry_time:
        return False

    if center.expiry_time >= now_eat():
        return False

    current_session = center.current_session_id

    AidTokens.query.filter(
        AidTokens.distribution_center_id == center.id,
        AidTokens.session_id == current_session,
        AidTokens.token_status.in_(["pending", "active"]),
    ).update(
        {"token_status": "expired"},
        synchronize_session=False,
    )

    center.is_active = False
    center.start_time = None
    center.expiry_time = None
    center.current_session_id = None

    db.session.commit()

    log_action(
        None,
        "Distribution Session Auto-Expired",
        f"Session for {center.aid_center_name} was automatically ended "
        f"because its expiry time was reached.",
    )

    return True