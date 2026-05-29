"""
routes/workspaces.py — Workspace RBAC API.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_active_workspace_dep
from app.core.errors import KnowForgeError
from app.db.models import User, Workspace, WorkspaceMember
from app.db.session import get_db
from app.schemas.workspace import (
    InviteCreate,
    InviteOut,
    MemberRoleUpdate,
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspaceSwitchRequest,
)
from app.services.workspace import (
    create_invite,
    create_workspace,
    get_member,
    list_user_workspaces,
    require_role,
    switch_workspace,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _ws_out(ws: Workspace, role: str | None = None) -> WorkspaceOut:
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        slug=ws.slug,
        is_personal=ws.is_personal,
        created_at=ws.created_at,
        your_role=role,  # type: ignore[arg-type]
    )


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceListResponse:
    pairs = list_user_workspaces(db, user)
    return WorkspaceListResponse(
        workspaces=[_ws_out(ws, m.role) for ws, m in pairs],
        active_workspace_id=user.active_workspace_id,
    )


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace_route(
    payload: WorkspaceCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceOut:
    ws, member = create_workspace(db, user, payload.name)
    return _ws_out(ws, member.role)


@router.post("/switch", response_model=WorkspaceOut)
def switch_workspace_route(
    payload: WorkspaceSwitchRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceOut:
    ws = switch_workspace(db, user, payload.workspace_id)
    member = get_member(db, workspace_id=ws.id, user_id=user.id)
    return _ws_out(ws, member.role if member else None)


@router.post("/{workspace_id}/switch", response_model=WorkspaceOut)
def switch_workspace_by_id_route(
    workspace_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceOut:
    ws = switch_workspace(db, user, workspace_id)
    member = get_member(db, workspace_id=ws.id, user_id=user.id)
    return _ws_out(ws, member.role if member else None)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
def list_members(
    workspace_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceMemberOut]:
    member = get_member(db, workspace_id=workspace_id, user_id=user.id)
    require_role(member, "viewer")
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise KnowForgeError("Workspace not found.", status_code=404, code="workspace_not_found")
    return [
        WorkspaceMemberOut(
            id=m.id,
            user_id=m.user_id,
            user_name=m.user.name,
            user_email=m.user.email,
            role=m.role,  # type: ignore[arg-type]
            created_at=m.created_at,
        )
        for m in ws.members
    ]


@router.patch("/{workspace_id}/members/{member_id}", response_model=WorkspaceMemberOut)
def update_member_role(
    workspace_id: str,
    member_id: str,
    payload: MemberRoleUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMemberOut:
    requester = get_member(db, workspace_id=workspace_id, user_id=user.id)
    require_role(requester, "admin")
    target: WorkspaceMember | None = db.get(WorkspaceMember, member_id)
    if not target or target.workspace_id != workspace_id:
        raise KnowForgeError("Member not found.", status_code=404, code="member_not_found")
    target.role = payload.role
    db.commit()
    return WorkspaceMemberOut(
        id=target.id,
        user_id=target.user_id,
        user_name=target.user.name,
        user_email=target.user.email,
        role=target.role,  # type: ignore[arg-type]
        created_at=target.created_at,
    )


@router.delete("/{workspace_id}/members/{member_id}", response_model=dict)
def remove_member(
    workspace_id: str,
    member_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    requester = get_member(db, workspace_id=workspace_id, user_id=user.id)
    require_role(requester, "admin")
    target: WorkspaceMember | None = db.get(WorkspaceMember, member_id)
    if not target or target.workspace_id != workspace_id:
        raise KnowForgeError("Member not found.", status_code=404, code="member_not_found")
    if target.role == "owner":
        raise KnowForgeError("Cannot remove the workspace owner.", status_code=400, code="cannot_remove_owner")
    db.delete(target)
    db.commit()
    return {"removed": True}


@router.post("/{workspace_id}/invites", response_model=InviteOut, status_code=201)
def invite_member(
    workspace_id: str,
    payload: InviteCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InviteOut:
    member = get_member(db, workspace_id=workspace_id, user_id=user.id)
    require_role(member, "admin")
    invite = create_invite(
        db,
        workspace_id=workspace_id,
        email=payload.email,
        role=payload.role,
        invited_by=user.id,
    )
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,  # type: ignore[arg-type]
        code=invite.code,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.delete("/{workspace_id}", response_model=dict)
def delete_workspace_route(
    workspace_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    requester = get_member(db, workspace_id=workspace_id, user_id=user.id)
    require_role(requester, "admin")

    # Check how many workspaces the requester has memberships in
    user_memberships = db.query(WorkspaceMember).filter_by(user_id=user.id).all()
    if len(user_memberships) <= 1:
        raise KnowForgeError(
            "Cannot delete workspace. You must have at least one active workspace.",
            status_code=400,
            code="cannot_delete_only_workspace",
        )

    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise KnowForgeError("Workspace not found.", status_code=404, code="workspace_not_found")

    # For every user that is a member of this workspace: update active_workspace_id if it's being deleted
    members = db.query(WorkspaceMember).filter_by(workspace_id=workspace_id).all()
    for member in members:
        user_to_update = member.user
        if user_to_update.active_workspace_id == workspace_id:
            # Find their first remaining workspace
            other_m = db.query(WorkspaceMember).filter(
                WorkspaceMember.user_id == user_to_update.id,
                WorkspaceMember.workspace_id != workspace_id
            ).first()
            if other_m:
                user_to_update.active_workspace_id = other_m.workspace_id
            else:
                user_to_update.active_workspace_id = None

    # Delete filesystem data
    import shutil
    from pathlib import Path
    from app.core.config import settings
    storage_root = Path(settings.knowforge_storage_path)
    workspace_dir = storage_root / "workspaces" / workspace_id
    if workspace_dir.exists() and workspace_dir.is_dir():
        shutil.rmtree(workspace_dir)

    # Delete workspace in database
    db.delete(ws)
    db.commit()

    return {"deleted": True}
