from flask import session
from datetime import datetime, date

from app import db  # Added db import to resolve database function errors
from app.models import Users, Household, DistributionCenter, AidTokens, AuditLog


def get_dashboard_data():
    """
    Returns all dashboard statistics and metrics for the admin dashboard.
    """
    # Core Beneficiary & Worker Statistics
    registered_beneficiaries = Users.query.filter_by(role="beneficiary").count()
    aid_workers = Users.query.filter_by(role="aid_worker").count()
    active_workers = Users.query.filter_by(role="aid_worker", is_active=True).count()
    inactive_workers = Users.query.filter_by(role="aid_worker", is_active=False).count()
    
    households = Household.query.count()
    audit_logs = AuditLog.query.count()

    # Token Statistics
    active_tokens = AidTokens.query.filter_by(token_status="active").count()
    used_tokens = AidTokens.query.filter_by(token_status="used").count()
    inactive_tokens = AidTokens.query.filter_by(token_status="inactive").count()
    total_tokens = active_tokens + used_tokens + inactive_tokens

    tokens_issued_today = AidTokens.query.filter(
        db.func.date(AidTokens.token_issued_at) == date.today()
    ).count()

    redeemed_tokens = used_tokens
    expired_tokens = inactive_tokens
    pending_tokens = active_tokens

    # Distribution Center Statistics
    centers = DistributionCenter.query.order_by(
        DistributionCenter.aid_center_name
    ).all()
    distribution_centers = len(centers)
    active_centers = DistributionCenter.query.filter_by(is_active=True).count()
    inactive_centers = DistributionCenter.query.filter_by(is_active=False).count()

    # Distribution Center Summary 
    center_summary = []
    center_labels = []
    household_counts = []

    for center in centers:
        beneficiary_count = Household.query.filter_by(center_id=center.id).count()
        
        # Only include centers that have beneficiaries assigned
        if beneficiary_count > 0:
            center_summary.append({
                "name": center.aid_center_name,
                "beneficiary_count": beneficiary_count
            })

            center_labels.append(center.aid_center_name)
            household_counts.append(beneficiary_count)

    # Officer Workload 
    officer_summary = []
    workers = Users.query.filter_by(role="aid_worker").all()

    for worker in workers:
        beneficiary_count = Household.query.filter_by(
            center_id=worker.assigned_center_id
        ).count()

        # Only include officers whose assigned center has beneficiaries
        if beneficiary_count > 0:
            officer_summary.append({
                "name": f"{worker.first_name} {worker.second_name}",
                "beneficiary_count": beneficiary_count
            })

    # Recent Activities (Audit Logs)
    recent_activities = (
        AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(20).all()
    )

    # Calculate Percentages
    total_households = Household.query.count() if Household.query.count() > 0 else 1
    
    beneficiary_percentage = min(
        (
            int((registered_beneficiaries / total_households) * 100)
            if total_households > 0
            else 0
        ),
        100,
    )

    token_percentage = min(
        int((used_tokens / total_tokens) * 100) if total_tokens > 0 else 0, 100
    )

    center_utilization = min(
        (
            int((active_centers / distribution_centers) * 100)
            if distribution_centers > 0
            else 0
        ),
        100,
    )

    # Return Dashboard Data Dictionary
    return {
        "admin_name": session.get("admin_name"),
        "now": datetime.now(),
        # Core Statistics
        "registered_beneficiaries": registered_beneficiaries,
        "aid_workers": aid_workers,
        "households": households,
        "distribution_centers": distribution_centers,
        # Token Statistics
        "active_tokens": active_tokens,
        "used_tokens": used_tokens,
        "inactive_tokens": inactive_tokens,
        "total_tokens": total_tokens,
        "tokens_issued_today": tokens_issued_today,
        "redeemed_tokens": redeemed_tokens,
        "expired_tokens": expired_tokens,
        "pending_tokens": pending_tokens,
        # Audit & Activity
        "audit_logs": audit_logs,
        "recent_activities": recent_activities,
        "active_workers": active_workers,
        "inactive_workers": inactive_workers,
        "active_centers": active_centers,
        "inactive_centers": inactive_centers,
        # Summaries & Chart Data
        "center_summary": center_summary,
        "officer_summary": officer_summary,
        "center_labels": center_labels,
        "household_counts": household_counts,
        # Percentages
        "beneficiary_percentage": beneficiary_percentage,
        "token_percentage": token_percentage,
        "center_utilization": center_utilization,
        # System Info
        "active_sessions": 1,
    }