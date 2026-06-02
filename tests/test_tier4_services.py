from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import WikiFactEvent
from app.services.tier4 import fact_status


def _fact(expiration_date=None, review_status="pending_review"):
    return WikiFactEvent(
        workspace_id="ws",
        page_slug="page",
        fact_type="deadline",
        subject="Subject",
        predicate="expires",
        object_val="Value",
        expiration_date=expiration_date,
        review_status=review_status,
    )


def test_fact_status_categories_temporal_risk():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    assert fact_status(_fact(now - timedelta(days=1)), now=now, days_ahead=30) == "expired"
    assert fact_status(_fact(now + timedelta(days=10)), now=now, days_ahead=30) == "expiring"
    assert fact_status(_fact(now + timedelta(days=90)), now=now, days_ahead=30) == "current"
    assert fact_status(_fact(None), now=now, days_ahead=30) == "undated"
    assert fact_status(_fact(now - timedelta(days=1), "reviewed"), now=now, days_ahead=30) == "reviewed"
