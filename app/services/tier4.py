from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.mailer import send_plain_email
from app.db.models import (
    ChatMessageRecord,
    ChatSession,
    FlashCard,
    FlashCardReview,
    KnowledgeDigest,
    KnowledgeHealthSnapshot,
    Notification,
    User,
    WikiFactEvent,
    WikiPageRecord,
    WikiPageVersion,
    Workspace,
    WorkspaceMember,
    utc_now,
)
from app.llmwiki.contradictions import ContradictionStore
from app.llmwiki.storage import WikiStore
from app.schemas.llmwiki import WikiPage

FactStatus = Literal["expired", "expiring", "current", "undated", "reviewed"]


def _loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _as_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def fact_status(fact: WikiFactEvent, *, now: datetime | None = None, days_ahead: int | None = None) -> FactStatus:
    if fact.review_status == "reviewed":
        return "reviewed"
    now = now or utc_now()
    days_ahead = days_ahead if days_ahead is not None else settings.tier4_fact_expiring_days
    expires = _as_utc(fact.expiration_date)
    if not expires:
        return "undated"
    if expires < now:
        return "expired"
    if expires <= now + timedelta(days=days_ahead):
        return "expiring"
    return "current"


class FactTimelineService:
    def __init__(self, db: Session):
        self.db = db

    def list_timeline(self, *, workspace_id: str, days_ahead: int, status: str = "all") -> dict[str, Any]:
        now = utc_now()
        rows = (
            self.db.query(WikiFactEvent)
            .filter(WikiFactEvent.workspace_id == workspace_id)
            .order_by(WikiFactEvent.expiration_date.is_(None), WikiFactEvent.expiration_date.asc(), WikiFactEvent.created_at.desc())
            .all()
        )
        items: list[dict[str, Any]] = []
        counts = {"expired": 0, "expiring": 0, "current": 0, "undated": 0, "reviewed": 0}
        for fact in rows:
            item_status = fact_status(fact, now=now, days_ahead=days_ahead)
            counts[item_status] += 1
            if status != "all" and item_status != status:
                continue
            days_until = None
            if fact.expiration_date:
                days_until = (_as_utc(fact.expiration_date).date() - now.date()).days  # type: ignore[union-attr]
            items.append({
                "id": fact.id,
                "page_slug": fact.page_slug,
                "fact_type": fact.fact_type,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object_val": fact.object_val,
                "effective_date": fact.effective_date.isoformat() if fact.effective_date else None,
                "expiration_date": fact.expiration_date.isoformat() if fact.expiration_date else None,
                "source_quote": fact.source_quote,
                "confidence": fact.confidence,
                "status": item_status,
                "days_until_expiration": days_until,
                "review_status": fact.review_status,
                "reviewed_at": fact.reviewed_at.isoformat() if fact.reviewed_at else None,
                "review_note": fact.review_note,
            })
        return {"items": items, "counts": counts, "days_ahead": days_ahead, "generated_at": now.isoformat()}

    def mark_reviewed(self, *, fact_id: str, workspace_id: str, user_id: str, review_note: str = "") -> dict[str, Any] | None:
        fact = (
            self.db.query(WikiFactEvent)
            .filter(WikiFactEvent.id == fact_id, WikiFactEvent.workspace_id == workspace_id)
            .first()
        )
        if not fact:
            return None
        fact.review_status = "reviewed"
        fact.reviewed_at = utc_now()
        fact.reviewed_by = user_id
        fact.review_note = review_note[:2000]
        self.db.commit()
        return self.list_timeline(workspace_id=workspace_id, days_ahead=settings.tier4_fact_expiring_days, status="all")

    def mark_many_reviewed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        status: str = "all",
        days_ahead: int | None = None,
        review_note: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        days_ahead = days_ahead if days_ahead is not None else settings.tier4_fact_expiring_days
        rows = (
            self.db.query(WikiFactEvent)
            .filter(WikiFactEvent.workspace_id == workspace_id, WikiFactEvent.review_status != "reviewed")
            .all()
        )
        selected = [fact for fact in rows if status == "all" or fact_status(fact, now=now, days_ahead=days_ahead) == status]
        for fact in selected:
            fact.review_status = "reviewed"
            fact.reviewed_at = now
            fact.reviewed_by = user_id
            fact.review_note = review_note[:2000]
        self.db.commit()
        payload = self.list_timeline(workspace_id=workspace_id, days_ahead=days_ahead, status=status)
        payload["reviewed_count"] = len(selected)
        return payload


class KnowledgeHealthScorer:
    def __init__(self, db: Session, store: WikiStore):
        self.db = db
        self.store = store

    def calculate(self, *, workspace_id: str, persist: bool = True) -> dict[str, Any]:
        now = utc_now()
        pages = self.store.list_pages()
        total_pages = len(pages)
        records = self.db.query(WikiPageRecord).filter_by(workspace_id=workspace_id).all()
        recent_cutoff = now - timedelta(days=45)
        recent_pages = sum(1 for r in records if _as_utc(r.updated_at) and _as_utc(r.updated_at) >= recent_cutoff)
        freshness = 100 if total_pages == 0 else (recent_pages / max(total_pages, 1)) * 100

        conflicts = ContradictionStore(self.store).list_open()
        severity_weight = {"low": 4, "medium": 9, "high": 18}
        conflict_penalty = sum(severity_weight.get(c.severity, 9) for c in conflicts)
        accuracy = 100 - conflict_penalty
        high_conf = sum(1 for p in pages if getattr(p, "confidence", "medium") == "high")
        med_conf = sum(1 for p in pages if getattr(p, "confidence", "medium") == "medium")
        completeness = 100 if total_pages == 0 else ((high_conf + med_conf * 0.7) / total_pages) * 100

        facts = self.db.query(WikiFactEvent).filter_by(workspace_id=workspace_id).all()
        expired = sum(1 for f in facts if fact_status(f, now=now) == "expired")
        expiring = sum(1 for f in facts if fact_status(f, now=now) == "expiring")
        staleness = 100 - (expired * 12 + expiring * 5)
        high_conflicts = sum(1 for c in conflicts if c.severity == "high")
        integrity = 100 - (high_conflicts * 22 + max(0, len(conflicts) - high_conflicts) * 6)

        scores = {
            "freshness_score": _clamp_score(freshness),
            "accuracy_score": _clamp_score(accuracy),
            "completeness_score": _clamp_score(completeness),
            "staleness_score": _clamp_score(staleness),
            "integrity_score": _clamp_score(integrity),
        }
        overall = _clamp_score(
            scores["freshness_score"] * 0.2
            + scores["accuracy_score"] * 0.25
            + scores["completeness_score"] * 0.15
            + scores["staleness_score"] * 0.25
            + scores["integrity_score"] * 0.15
        )
        action_items = self._action_items(conflicts, expired, expiring, total_pages, recent_pages)
        previous = (
            self.db.query(KnowledgeHealthSnapshot)
            .filter_by(workspace_id=workspace_id)
            .order_by(KnowledgeHealthSnapshot.created_at.desc())
            .first()
        )
        trend_delta = overall - previous.overall_score if previous else 0
        trend = "flat" if trend_delta == 0 else "up" if trend_delta > 0 else "down"
        if persist:
            snap = KnowledgeHealthSnapshot(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                overall_score=overall,
                action_items_json=_dumps(action_items),
                **scores,
            )
            self.db.add(snap)
            self.db.commit()
        return {
            "overall_score": overall,
            **scores,
            "trend": trend,
            "trend_delta": trend_delta,
            "action_items": action_items,
            "counts": {"pages": total_pages, "open_conflicts": len(conflicts), "expired_facts": expired, "expiring_facts": expiring},
            "generated_at": now.isoformat(),
        }

    @staticmethod
    def _action_items(conflicts: list[Any], expired: int, expiring: int, total_pages: int, recent_pages: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if expired:
            items.append({"kind": "timeline", "priority": "high", "label": f"Review {expired} expired fact{'s' if expired != 1 else ''}."})
        if conflicts:
            high = sum(1 for c in conflicts if c.severity == "high")
            items.append({"kind": "conflict", "priority": "high" if high else "medium", "label": f"Resolve {len(conflicts)} open contradiction{'s' if len(conflicts) != 1 else ''}."})
        if expiring:
            items.append({"kind": "timeline", "priority": "medium", "label": f"Check {expiring} fact{'s' if expiring != 1 else ''} expiring soon."})
        if total_pages and recent_pages < total_pages:
            items.append({"kind": "freshness", "priority": "low", "label": "Refresh stale pages with newer source material."})
        return items[:5]


class DailyDigestService:
    def __init__(self, db: Session, store: WikiStore):
        self.db = db
        self.store = store

    def generate_for_user(self, *, workspace: Workspace, user: User, send_email: bool = True) -> KnowledgeDigest:
        today = utc_now().date()
        existing = (
            self.db.query(KnowledgeDigest)
            .filter_by(workspace_id=workspace.id, user_id=user.id, digest_date=today)
            .first()
        )
        if existing:
            return existing
        payload = self._build_payload(workspace_id=workspace.id, user_id=user.id)
        digest = KnowledgeDigest(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            user_id=user.id,
            digest_date=today,
            title="Daily Knowledge Digest",
            content_json=_dumps(payload),
        )
        self.db.add(digest)
        self.db.flush()
        notification = Notification(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            user_id=user.id,
            notification_type="daily_digest",
            title="Daily Knowledge Digest",
            body=payload.get("insight_of_the_day", "Your workspace digest is ready."),
            target_type="digest",
            target_id=digest.id,
            payload_json=_dumps({"digest_id": digest.id}),
        )
        self.db.add(notification)
        if send_email and settings.tier4_digest_email_enabled:
            sent = send_plain_email(user.email, f"KnowForge digest: {workspace.name}", self._email_body(workspace, payload))
            if sent:
                digest.email_sent_at = utc_now()
        self.db.commit()
        return digest

    def latest_for_user(self, *, workspace_id: str, user_id: str) -> KnowledgeDigest | None:
        return (
            self.db.query(KnowledgeDigest)
            .filter_by(workspace_id=workspace_id, user_id=user_id)
            .order_by(KnowledgeDigest.digest_date.desc(), KnowledgeDigest.created_at.desc())
            .first()
        )

    def _build_payload(self, *, workspace_id: str, user_id: str) -> dict[str, Any]:
        timeline = FactTimelineService(self.db).list_timeline(workspace_id=workspace_id, days_ahead=settings.tier4_fact_expiring_days)
        risky = [i for i in timeline["items"] if i["status"] in {"expired", "expiring"}][:8]
        conflicts = [c.model_dump() for c in ContradictionStore(self.store).list_open()[:6]]
        since = utc_now() - timedelta(days=7)
        changed = (
            self.db.query(WikiPageRecord)
            .filter(WikiPageRecord.workspace_id == workspace_id, WikiPageRecord.updated_at >= since)
            .order_by(WikiPageRecord.updated_at.desc())
            .limit(8)
            .all()
        )
        chat_rows = (
            self.db.query(ChatMessageRecord)
            .join(ChatSession, ChatMessageRecord.session_id == ChatSession.id)
            .filter(ChatSession.workspace_id == workspace_id, ChatMessageRecord.user_id == user_id, ChatMessageRecord.role == "user", ChatMessageRecord.created_at >= since)
            .order_by(ChatMessageRecord.created_at.desc())
            .limit(20)
            .all()
        )
        topics = self._topic_suggestions([row.content for row in chat_rows])
        insight = "Your knowledge base is calm today."
        if risky:
            insight = f"{len(risky)} time-sensitive fact{'s' if len(risky) != 1 else ''} need attention."
        elif conflicts:
            insight = f"{len(conflicts)} open contradiction{'s' if len(conflicts) != 1 else ''} should be reviewed."
        return {
            "expiring_facts": risky,
            "new_conflicts": conflicts,
            "changed_pages": [{"slug": r.slug, "title": r.title, "updated_at": r.updated_at.isoformat()} for r in changed],
            "suggested_review_pages": topics,
            "insight_of_the_day": insight,
            "generated_at": utc_now().isoformat(),
        }

    def _topic_suggestions(self, messages: list[str]) -> list[dict[str, str]]:
        if not messages:
            return []
        text = " ".join(messages).lower()
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9_-]{3,}", text) if w not in {"what", "when", "where", "which", "about", "from", "this", "that", "with", "have", "need"}]
        ranked = sorted({w: words.count(w) for w in words}.items(), key=lambda x: x[1], reverse=True)[:5]
        pages = self.store.list_pages()
        suggestions = []
        for word, _count in ranked:
            match = next((p for p in pages if word in p.title.lower() or word in p.slug.lower()), None)
            if match:
                suggestions.append({"slug": match.slug, "title": match.title, "reason": f"You asked about {word} recently."})
        return suggestions[:4]

    @staticmethod
    def _email_body(workspace: Workspace, payload: dict[str, Any]) -> str:
        lines = [f"Daily Knowledge Digest for {workspace.name}", "", payload.get("insight_of_the_day", ""), ""]
        for label, key in (("Expiring facts", "expiring_facts"), ("Conflicts", "new_conflicts"), ("Changed pages", "changed_pages")):
            rows = payload.get(key, [])
            lines.append(f"{label}: {len(rows)}")
            for row in rows[:5]:
                lines.append(f"- {row.get('subject') or row.get('topic') or row.get('title') or row.get('page_slug', 'Item')}")
            lines.append("")
        return "\n".join(lines).strip()


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_user(self, *, workspace_id: str, user_id: str, limit: int = 20) -> dict[str, Any]:
        rows = (
            self.db.query(Notification)
            .filter_by(workspace_id=workspace_id, user_id=user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )
        unread = self.db.query(Notification).filter_by(workspace_id=workspace_id, user_id=user_id, read_at=None).count()
        return {"unread_count": unread, "items": [self._out(n) for n in rows]}

    def mark_read(self, *, notification_id: str, workspace_id: str, user_id: str) -> Notification | None:
        row = self.db.query(Notification).filter_by(id=notification_id, workspace_id=workspace_id, user_id=user_id).first()
        if not row:
            return None
        row.read_at = row.read_at or utc_now()
        self.db.commit()
        return row

    @staticmethod
    def _out(row: Notification) -> dict[str, Any]:
        return {
            "id": row.id,
            "type": row.notification_type,
            "title": row.title,
            "body": row.body,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "payload": _loads(row.payload_json, {}),
            "read_at": row.read_at.isoformat() if row.read_at else None,
            "created_at": row.created_at.isoformat(),
        }


class FlashcardService:
    def __init__(self, db: Session, store: WikiStore):
        self.db = db
        self.store = store

    def generate(self, *, workspace_id: str, user_id: str, page_slugs: list[str] | None = None) -> dict[str, Any]:
        all_slugs = page_slugs or [p.slug for p in self.store.list_pages()]
        # Keep generation bounded and deterministic so Review never waits on an LLM or a huge workspace.
        slugs = all_slugs[:30]
        created = 0
        skipped_pages = 0
        for slug in slugs:
            try:
                page = self.store.read_page(slug, prefer_compact=True)
            except Exception:
                skipped_pages += 1
                continue
            for card in self._cards_from_page(page)[:6]:
                source_hash = hashlib.sha256(f"{slug}|{card['question']}|{card['answer']}".encode()).hexdigest()[:32]
                exists = self.db.query(FlashCard).filter_by(workspace_id=workspace_id, source_hash=source_hash).first()
                if exists:
                    continue
                self.db.add(FlashCard(id=str(uuid.uuid4()), workspace_id=workspace_id, page_slug=slug, created_by=user_id, source_hash=source_hash, **card))
                created += 1
        self.db.commit()
        return {
            "created": created,
            "scanned_pages": len(slugs),
            "skipped_pages": skipped_pages,
            "limited": len(all_slugs) > len(slugs),
        }

    def due(self, *, workspace_id: str, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        now = utc_now()
        rows = (
            self.db.query(FlashCard, FlashCardReview)
            .outerjoin(
                FlashCardReview,
                and_(FlashCardReview.card_id == FlashCard.id, FlashCardReview.user_id == user_id),
            )
            .filter(
                FlashCard.workspace_id == workspace_id,
                or_(FlashCardReview.id.is_(None), FlashCardReview.next_review_date <= now),
            )
            .order_by(FlashCardReview.next_review_date.asc().nullsfirst(), FlashCard.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._card_out(card, progress) for card, progress in rows]

    def stats(self, *, workspace_id: str, user_id: str) -> dict[str, Any]:
        now = utc_now()
        total = self.db.query(FlashCard).filter_by(workspace_id=workspace_id).count()
        reviewed = (
            self.db.query(FlashCardReview)
            .join(FlashCard, FlashCardReview.card_id == FlashCard.id)
            .filter(FlashCard.workspace_id == workspace_id, FlashCardReview.user_id == user_id, FlashCardReview.last_reviewed_at.isnot(None))
            .count()
        )
        due_count = (
            self.db.query(FlashCard.id)
            .outerjoin(
                FlashCardReview,
                and_(FlashCardReview.card_id == FlashCard.id, FlashCardReview.user_id == user_id),
            )
            .filter(
                FlashCard.workspace_id == workspace_id,
                or_(FlashCardReview.id.is_(None), FlashCardReview.next_review_date <= now),
            )
            .count()
        )
        mastered = (
            self.db.query(FlashCardReview)
            .join(FlashCard, FlashCardReview.card_id == FlashCard.id)
            .filter(FlashCard.workspace_id == workspace_id, FlashCardReview.user_id == user_id, FlashCardReview.interval_days >= 14)
            .count()
        )
        return {"total_cards": total, "reviewed_cards": reviewed, "due_today": due_count, "mastery_percent": 0 if total == 0 else round((mastered / total) * 100)}

    def review(self, *, card_id: str, workspace_id: str, user_id: str, result: str) -> dict[str, Any] | None:
        if result not in {"again", "hard", "easy"}:
            result = "hard"
        card = self.db.query(FlashCard).filter_by(id=card_id, workspace_id=workspace_id).first()
        if not card:
            return None
        try:
            progress = self._progress(card_id, user_id)
            now = utc_now()
            if result == "again":
                progress.repetitions = 0
                progress.interval_days = 1
                progress.ease_factor = max(1.3, progress.ease_factor - 0.2)
            elif result == "hard":
                progress.repetitions += 1
                progress.interval_days = max(1, int(max(1, progress.interval_days) * 1.2))
                progress.ease_factor = max(1.3, progress.ease_factor - 0.1)
            else:
                progress.repetitions += 1
                progress.interval_days = 1 if progress.repetitions == 1 else max(2, int(max(1, progress.interval_days) * progress.ease_factor))
                progress.ease_factor = min(3.0, progress.ease_factor + 0.05)
            progress.next_review_date = now + timedelta(days=progress.interval_days)
            progress.last_reviewed_at = now
            progress.last_result = result
            history = _loads(progress.result_history_json, [])
            history.append({"result": result, "reviewed_at": now.isoformat(), "interval_days": progress.interval_days})
            progress.result_history_json = _dumps(history[-50:])
            self.db.commit()
            return self._card_out(card, progress)
        except Exception:
            self.db.rollback()
            raise

    def _progress(self, card_id: str, user_id: str) -> FlashCardReview:
        row = self.db.query(FlashCardReview).filter_by(card_id=card_id, user_id=user_id).first()
        if row:
            return row
        row = FlashCardReview(id=str(uuid.uuid4()), card_id=card_id, user_id=user_id, next_review_date=utc_now())
        self.db.add(row)
        self.db.flush()
        return row

    @staticmethod
    def _card_out(card: FlashCard, progress: FlashCardReview | None) -> dict[str, Any]:
        return {
            "id": card.id,
            "page_slug": card.page_slug,
            "question": card.question,
            "answer": card.answer,
            "difficulty": card.difficulty,
            "source_quote": card.source_quote,
            "ease_factor": progress.ease_factor if progress else 2.5,
            "interval_days": progress.interval_days if progress else 0,
            "next_review_date": (progress.next_review_date if progress else utc_now()).isoformat(),
        }

    @staticmethod
    def _cards_from_page(page: WikiPage) -> list[dict[str, str]]:
        title = page.meta.title
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page.content) if len(p.strip()) > 80]
        cards = []
        for para in paragraphs[:8]:
            clean = re.sub(r"[#*_`>\[\]]", "", para).strip()
            sentence = re.split(r"(?<=[.!?])\s+", clean)[0][:600]
            if len(sentence) < 50:
                continue
            cards.append({
                "question": f"What should you remember about {title}?",
                "answer": sentence,
                "difficulty": "medium",
                "source_quote": sentence[:1000],
            })
        return cards


def digest_out(row: KnowledgeDigest | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.id,
        "title": row.title,
        "digest_date": row.digest_date.isoformat(),
        "content": _loads(row.content_json, {}),
        "email_sent_at": row.email_sent_at.isoformat() if row.email_sent_at else None,
        "created_at": row.created_at.isoformat(),
    }


def stale_fact_warning(db: Session, *, workspace_id: str, page_slugs: list[str]) -> str:
    if not page_slugs:
        return ""
    now = utc_now()
    count = (
        db.query(WikiFactEvent)
        .filter(
            WikiFactEvent.workspace_id == workspace_id,
            WikiFactEvent.page_slug.in_(page_slugs),
            WikiFactEvent.review_status != "reviewed",
            WikiFactEvent.expiration_date.isnot(None),
            WikiFactEvent.expiration_date < now,
        )
        .count()
    )
    if not count:
        return ""
    return f"Note: {count} fact{'s' if count != 1 else ''} related to this answer have expired and may need review.\n\n"
