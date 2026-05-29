"""
services/workspace.py — Workspace lifecycle management.

Handles:
  - Auto-creating a personal workspace on user signup/first login.
  - Migrating existing file storage from users/{uid} → workspaces/{wid}.
  - Looking up a user's active workspace.
  - RBAC enforcement helpers.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import KnowForgeError
from app.db.models import User, Workspace, WorkspaceInvite, WorkspaceMember
from app.llmwiki.text import slugify

ROLE_HIERARCHY = {"owner": 4, "admin": 3, "editor": 2, "viewer": 1}


def role_rank(role: str) -> int:
    return ROLE_HIERARCHY.get(role, 0)


def require_role(member: WorkspaceMember | None, minimum_role: str) -> None:
    if not member:
        raise KnowForgeError("Not a member of this workspace.", status_code=403, code="not_member")
    if role_rank(member.role) < role_rank(minimum_role):
        raise KnowForgeError(
            f"Requires {minimum_role} role or higher.",
            status_code=403,
            code="insufficient_role",
        )


def get_member(db: Session, *, workspace_id: str, user_id: str) -> WorkspaceMember | None:
    return (
        db.query(WorkspaceMember)
        .filter_by(workspace_id=workspace_id, user_id=user_id)
        .first()
    )


def ensure_personal_workspace(db: Session, user: User) -> Workspace:
    """
    Create (or find) the user's personal workspace and update
    `user.active_workspace_id`. Also migrates legacy file storage.
    """
    # If already has an active workspace, just return it
    if user.active_workspace_id:
        ws = db.get(Workspace, user.active_workspace_id)
        if ws:
            return ws

    # Look for existing personal workspace membership
    for membership in user.workspace_memberships:
        ws = membership.workspace
        if ws and ws.is_personal:
            if not user.active_workspace_id:
                user.active_workspace_id = ws.id
                db.commit()
            return ws

    # Create new personal workspace
    ws_slug = f"personal-{user.id[:8]}"
    ws = Workspace(
        id=str(uuid.uuid4()),
        name=f"{user.name}'s Workspace",
        slug=ws_slug,
        is_personal=True,
    )
    db.add(ws)
    db.flush()

    member = WorkspaceMember(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        user_id=user.id,
        role="owner",
    )
    db.add(member)
    user.active_workspace_id = ws.id
    db.commit()

    # Migrate legacy user wiki files → workspace folder
    _migrate_user_storage(user_id=user.id, workspace_id=ws.id)

    return ws


def _migrate_user_storage(user_id: str, workspace_id: str) -> None:
    """Move storage/users/{uid}/* → storage/workspaces/{wid}/"""
    storage_root = Path(settings.knowforge_storage_path)
    old_dir = storage_root / "users" / user_id
    new_dir = storage_root / "workspaces" / workspace_id
    if old_dir.exists() and not new_dir.exists():
        import shutil
        shutil.copytree(str(old_dir), str(new_dir))


def get_active_workspace(db: Session, user: User) -> Workspace:
    ws = ensure_personal_workspace(db, user)
    if user.active_workspace_id and user.active_workspace_id != ws.id:
        active = db.get(Workspace, user.active_workspace_id)
        if active:
            return active
    return ws


def switch_workspace(db: Session, user: User, workspace_id: str) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise KnowForgeError("Workspace not found.", status_code=404, code="workspace_not_found")
    member = get_member(db, workspace_id=workspace_id, user_id=user.id)
    if not member:
        raise KnowForgeError("Not a member of this workspace.", status_code=403, code="not_member")
    user.active_workspace_id = workspace_id
    db.commit()
    return ws


def create_workspace(db: Session, user: User, name: str) -> tuple[Workspace, WorkspaceMember]:
    ws_slug = slugify(name) + "-" + user.id[:6]
    ws = Workspace(
        id=str(uuid.uuid4()),
        name=name,
        slug=ws_slug,
        is_personal=False,
    )
    db.add(ws)
    db.flush()
    member = WorkspaceMember(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        user_id=user.id,
        role="owner",
    )
    db.add(member)
    db.commit()
    return ws, member


def create_invite(
    db: Session,
    *,
    workspace_id: str,
    email: str,
    role: str,
    invited_by: str,
) -> WorkspaceInvite:
    code = secrets.token_urlsafe(16)
    invite = WorkspaceInvite(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        email=email,
        role=role,
        invited_by=invited_by,
        code=code,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    return invite


def list_user_workspaces(
    db: Session, user: User
) -> list[tuple[Workspace, WorkspaceMember]]:
    result = []
    for membership in user.workspace_memberships:
        ws = membership.workspace
        if ws:
            result.append((ws, membership))
    return result
