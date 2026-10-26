"""Route-level aliases: every endpoint composes one of these, so an unscoped route can't be written by accident."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.deps import (
    CurrentUser,
    DbSession,
    PageQuery,
    ScopeDep,
    require_any_perm,
    require_perm,
)
from app.domain import permissions as P
from app.models.auth import User

# Permission aliases (403 for missing perms; Scope still decides 404 for foreign rows).
LeadsView = Annotated[User, Depends(require_any_perm(P.LEADS_VIEW_OWN, P.LEADS_VIEW_ALL))]
LeadsConvert = Annotated[User, Depends(require_perm(P.LEADS_CONVERT))]
LeadsAssign = Annotated[User, Depends(require_perm(P.LEADS_ASSIGN))]
ClientsView = Annotated[User, Depends(require_any_perm(P.CLIENTS_VIEW_OWN, P.CLIENTS_VIEW_ALL))]
ClientsManage = Annotated[User, Depends(require_perm(P.CLIENTS_MANAGE))]
InsuredManage = Annotated[User, Depends(require_perm(P.INSURED_MANAGE))]
RequestsView = Annotated[User, Depends(require_perm(P.REQUESTS_VIEW))]
RequestsManage = Annotated[User, Depends(require_perm(P.REQUESTS_MANAGE))]
CallsListen = Annotated[User, Depends(require_perm(P.CALLS_LISTEN))]
PoliciesView = Annotated[User, Depends(require_any_perm(P.POLICIES_VIEW, P.POLICIES_MANAGE))]
ReportsView = Annotated[User, Depends(require_perm(P.REPORTS_VIEW))]
SettingsManage = Annotated[User, Depends(require_perm(P.SETTINGS_MANAGE))]

__all__ = [
    "CallsListen",
    "ClientsManage",
    "ClientsView",
    "CurrentUser",
    "DbSession",
    "InsuredManage",
    "LeadsAssign",
    "LeadsConvert",
    "LeadsView",
    "PageQuery",
    "PoliciesView",
    "ReportsView",
    "RequestsManage",
    "RequestsView",
    "ScopeDep",
    "SettingsManage",
    "require_any_perm",
    "require_perm",
]
