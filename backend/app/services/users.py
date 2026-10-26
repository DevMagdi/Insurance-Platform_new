"""Users, roles, permissions and scopes administration (screen 15)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.scope import Scope
from app.core.security import hash_password
from app.domain import permissions as P
from app.domain.enums import PortalRole, ScopeType
from app.domain.phone import normalize_mobile
from app.models.auth import ClientPortalUser, Permission, Role, User, UserScope, role_permissions
from app.services import audit


async def list_users(session: AsyncSession, scope: Scope) -> list[dict[str, Any]]:
    if not scope.can("users.manage"):
        raise ValidationFailed("Not allowed")
    rows = (await session.execute(select(User).join(Role, Role.id == User.role_id).order_by(User.full_name))).scalars().all()
    out: list[dict[str, Any]] = []
    for user in rows:
        scopes = await _scope_names(session, user.id)
        out.append(
            {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "mobile": user.mobile,
                "role": user.role.code,
                "role_name": user.role.name,
                "is_active": user.is_active,
                "mfa_enabled": user.mfa_enabled,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "scopes": scopes,
                "portal_client_id": str(user.portal_link.client_id) if user.portal_link else None,
            }
        )
    return out


async def _scope_names(session: AsyncSession, user_id: UUID) -> list[dict[str, str]]:
    from app.models.clients import Client
    from app.models.masters import Insurer

    rows = (await session.execute(select(UserScope).where(UserScope.user_id == user_id))).scalars().all()
    out = []
    for row in rows:
        label = None
        if row.scope_type is ScopeType.CLIENT:
            label = (await session.execute(select(Client.name).where(Client.id == row.scope_id))).scalar_one_or_none()
        else:
            label = (await session.execute(select(Insurer.name).where(Insurer.id == row.scope_id))).scalar_one_or_none()
        out.append({"type": row.scope_type.value, "id": str(row.scope_id), "label": label or str(row.scope_id)})
    return out


async def create_user(session: AsyncSession, actor: User, payload: dict[str, Any], *, ip: str | None = None) -> User:
    email = str(payload["email"]).strip().lower()
    if (await session.execute(select(User.id).where(func.lower(User.email) == email))).scalar_one_or_none():
        raise Conflict("A user with this email already exists")
    role = (await session.execute(select(Role).where(Role.code == payload["role_code"]))).scalar_one_or_none()
    if role is None:
        raise ValidationFailed("Unknown role", details={"role_code": payload["role_code"]})
    password = str(payload.get("password") or "")
    if len(password) < 10:
        raise ValidationFailed("Password must be at least 10 characters")
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=payload["full_name"],
        mobile=normalize_mobile(payload.get("mobile")),
        # assign the relationship, not just the FK: callers read `user.role.code` after the commit and
        # a lazy load there would raise MissingGreenlet inside the async session
        role=role,
        is_active=bool(payload.get("is_active", True)),
    )
    session.add(user)
    await session.flush()

    if payload.get("portal_client_id"):
        user.portal_link = ClientPortalUser(user_id=user.id, client_id=UUID(str(payload["portal_client_id"])), portal_role=PortalRole.OWNER)
        await session.flush()
    for scope_entry in payload.get("scopes") or []:
        session.add(UserScope(user_id=user.id, scope_type=ScopeType(scope_entry["type"]), scope_id=UUID(str(scope_entry["id"]))))
    await session.flush()
    await audit.write(
        session,
        actor=actor,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        after={"email": user.email, "role": role.code},
        ip=ip,
    )
    return user


async def update_user(session: AsyncSession, actor: User, user_id: UUID, payload: dict[str, Any], *, ip: str | None = None) -> User:
    user = (
        await session.execute(select(User).where(User.id == user_id).options(selectinload(User.role).selectinload(Role.permissions)))
    ).scalar_one_or_none()
    if user is None or user.deleted_at is not None:
        raise NotFound("User not found")
    before = {"role": user.role.code, "is_active": user.is_active}
    if payload.get("role_code"):
        role = (await session.execute(select(Role).where(Role.code == payload["role_code"]))).scalar_one_or_none()
        if role is None:
            raise ValidationFailed("Unknown role")
        user.role_id = role.id
    if payload.get("full_name"):
        user.full_name = payload["full_name"]
    if "mobile" in payload:
        user.mobile = normalize_mobile(payload["mobile"])
    if "is_active" in payload and payload["is_active"] is not None:
        if user.id == actor.id and payload["is_active"] is False:
            raise Conflict("You cannot deactivate your own account")
        user.is_active = bool(payload["is_active"])
    if payload.get("password"):
        if len(str(payload["password"])) < 10:
            raise ValidationFailed("Password must be at least 10 characters")
        user.password_hash = hash_password(str(payload["password"]))
        user.refresh_token_version += 1  # a password change invalidates existing sessions
    await session.flush()
    await audit.write(
        session,
        actor=actor,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after={"role": user.role.code, "is_active": user.is_active},
        ip=ip,
    )
    return user


async def set_scopes(session: AsyncSession, actor: User, user_id: UUID, scopes: list[dict[str, str]], *, ip: str | None = None) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    await session.execute(sa.delete(UserScope).where(UserScope.user_id == user_id))
    for entry in scopes:
        session.add(UserScope(user_id=user_id, scope_type=ScopeType(entry["type"]), scope_id=UUID(entry["id"])))
    await session.flush()
    await audit.write(
        session,
        actor=actor,
        action="user.scopes_updated",
        entity_type="user",
        entity_id=user_id,
        after={"count": len(scopes)},
        ip=ip,
    )


async def roles_with_permissions(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Role).options().order_by(Role.code))).scalars().all()
    return [
        {
            "id": str(role.id),
            "code": role.code,
            "name": role.name,
            "is_system": role.is_system,
            "permissions": sorted(p.code for p in role.permissions),
        }
        for role in rows
    ]


async def permissions(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Permission).order_by(Permission.code))).scalars().all()
    return [{"code": p.code, "description": p.description, "group": p.group} for p in rows]


async def set_role_permissions(session: AsyncSession, actor: User, role_id: UUID, codes: list[str], *, ip: str | None = None) -> Role:
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFound("Role not found")
    if role.code == "system_admin":
        raise Conflict("The system admin role cannot be edited from the UI")
    known = set(P.ALL_PERMISSIONS)
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise ValidationFailed("Unknown permission codes", details={"unknown": unknown})
    before = sorted(p.code for p in role.permissions)
    rows = (await session.execute(select(Permission).where(Permission.code.in_(codes)))).scalars().all()
    role.permissions = list(rows)
    await session.flush()
    keep = [p.id for p in rows] or [UUID(int=0)]
    await session.execute(
        sa.delete(role_permissions).where(role_permissions.c.role_id == role_id, role_permissions.c.permission_id.notin_(keep))
    )
    for user in (await session.execute(select(User).where(User.role_id == role_id))).scalars():
        user.refresh_token_version += 1  # permission change => sessions must re-auth
    await session.flush()
    await audit.write(
        session,
        actor=actor,
        action="role.permissions_updated",
        entity_type="role",
        entity_id=role.id,
        before={"permissions": before},
        after={"permissions": sorted(codes)},
        ip=ip,
    )
    return role


_ = P
