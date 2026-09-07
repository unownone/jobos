"""Role write rules. Discovery creates; later lanes only advance their fields."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.constants import (
    ADMIN_FIELDS,
    APPLY_FIELDS,
    APPLY_LANE,
    CREATE_ROLES,
    DELETE_ROLES,
    DISCOVERY_FIELDS,
    DISCOVERY_LANE,
    HYGIENE_ROLES,
    IMPORT_ROLES,
    METRICS_READ_ROLES,
    OUTREACH_FIELDS,
    OUTREACH_LANE,
    PATCH_ROLES,
    STATUSES,
    STOP_ROLES,
)

OWNER_KEYS = ("discovery", "apply", "outreach")


def capabilities(role: str) -> dict[str, Any]:
    return {
        "role": role,
        "can_create": role in CREATE_ROLES,
        "can_patch": role in PATCH_ROLES,
        "can_stop": role in STOP_ROLES,
        "can_delete": role in DELETE_ROLES,
        "can_hygiene": role in HYGIENE_ROLES,
        "can_import": role in IMPORT_ROLES,
        "can_log_metrics": True,
        "can_read_metrics": role in METRICS_READ_ROLES,
        "patch_fields": sorted(_patch_fields_for(role)),
        "status_lane": sorted(_lane_for(role)),
    }


def ensure_can_create(role: str) -> None:
    if role not in CREATE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this role cannot create jobs (discovery creates; maintenance is read + hygiene)",
        )


def ensure_can_stop(role: str) -> None:
    if role not in STOP_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admin can stop a job",
        )


def ensure_can_delete(role: str) -> None:
    if role not in DELETE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admin can delete a job",
        )


def ensure_can_hygiene(role: str) -> None:
    if role not in HYGIENE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admin or maintenance can run hygiene",
        )


def ensure_can_import(role: str) -> None:
    if role not in IMPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admin or maintenance can import history",
        )


def ensure_can_read_metrics(role: str) -> None:
    if role not in METRICS_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admin or maintenance can read metrics summaries",
        )


def validate_status(value: str) -> str:
    if value not in STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status {value!r}; must be a jobOS process status",
        )
    return value


def merge_owners(current: dict[str, Any] | None, incoming: Any, role: str) -> dict[str, str]:
    merged = {"discovery": "", "apply": "", "outreach": ""}
    if isinstance(current, dict):
        for key in OWNER_KEYS:
            merged[key] = str(current.get(key) or "")
    if incoming is None:
        return merged
    if not isinstance(incoming, dict):
        raise HTTPException(
            status_code=422,
            detail="owners must be an object",
        )
    allowed = _owner_keys_for(role)
    extra = set(incoming) - set(OWNER_KEYS)
    if extra:
        raise HTTPException(
            status_code=422,
            detail=f"unknown owners keys: {sorted(extra)}",
        )
    forbidden = set(incoming) - allowed
    if forbidden and role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {role} cannot set owners.{sorted(forbidden)[0]}",
        )
    for key, value in incoming.items():
        if role == "admin" or key in allowed:
            merged[key] = "" if value is None else str(value)
    return merged


def authorize_patch(role: str, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if role not in PATCH_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this role cannot patch jobs",
        )
    if current.get("stopped") and role != "admin":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="job is stopped; only admin can edit",
        )
    allowed = _patch_fields_for(role)
    extra = set(incoming) - allowed
    if extra:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {role} cannot patch fields: {sorted(extra)}",
        )

    next_status = incoming.get("status", current.get("status"))
    if "status" in incoming:
        next_status = validate_status(str(incoming["status"]))
        lane = _lane_for(role)
        if role != "admin" and next_status not in lane:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {role} cannot set status {next_status}",
            )

    if role == "discovery":
        if current.get("status") not in DISCOVERY_LANE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="discovery cannot edit a job after it leaves the discovery lane",
            )
        if next_status not in DISCOVERY_LANE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="discovery can only keep the job in discovery-lane statuses",
            )

    patch: dict[str, Any] = {}
    for key, value in incoming.items():
        if key == "owners":
            patch["owners"] = merge_owners(current.get("owners"), value, role)
        elif key == "status":
            patch["status"] = next_status
        elif key == "stopped":
            if role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="only admin can set stopped",
                )
            patch["stopped"] = bool(value)
        else:
            patch[key] = value
    return patch


def authorize_create(role: str, incoming: dict[str, Any]) -> dict[str, Any]:
    ensure_can_create(role)
    allowed = ADMIN_FIELDS | {"id", "created_at", "updated_at"}
    if role != "admin":
        allowed = DISCOVERY_FIELDS | {"id", "created_at", "updated_at"}
    extra = set(incoming) - allowed
    if extra:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{role} cannot set fields: {sorted(extra)}",
        )
    status_value = incoming.get("status") or "discovered"
    validate_status(str(status_value))
    if role == "discovery" and status_value not in DISCOVERY_LANE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="discovery can only create jobs in the discovery lane",
        )
    if incoming.get("stopped") and role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admin can create a stopped job",
        )
    body = dict(incoming)
    body["status"] = status_value
    if "owners" in body:
        body["owners"] = merge_owners(None, body.get("owners"), role)
    return body


def _patch_fields_for(role: str) -> frozenset[str]:
    if role == "admin":
        return ADMIN_FIELDS
    if role == "discovery":
        return DISCOVERY_FIELDS - {"id"}
    if role == "apply":
        return APPLY_FIELDS
    if role == "outreach":
        return OUTREACH_FIELDS
    return frozenset()


def _lane_for(role: str) -> frozenset[str]:
    if role == "admin":
        return frozenset(STATUSES)
    if role == "discovery":
        return DISCOVERY_LANE
    if role == "apply":
        return APPLY_LANE
    if role == "outreach":
        return OUTREACH_LANE
    return frozenset()


def _owner_keys_for(role: str) -> set[str]:
    if role == "admin":
        return set(OWNER_KEYS)
    if role in OWNER_KEYS:
        return {role}
    return set()
