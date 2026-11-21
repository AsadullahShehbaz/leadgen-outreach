from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.db import get_session
from app.core.security import (
    encrypt_secret,
    hash_password,
    normalize_email,
)
from app.core.config import settings
from app.services.license.license import (
    InvalidLicense,
    check_mailbox_limit,
    verify_license_token,
)
from app.models import (
    Connection,
    Domain,
    LicenseState,
    Mailbox,
    User,
    Workspace,
)
from app.models.base import utcnow
from app.routers.auth import get_current_user
from app.schemas.setup import (
    SetupAdminRequest,
    SetupAdminResponse,
    SetupConnectionRequest,
    SetupConnectionResponse,
    SetupDomainRequest,
    SetupDomainResponse,
    SetupLicenseRequest,
    SetupLicenseResponse,
    SetupMailboxRequest,
    SetupMailboxResponse,
    SetupStatus,
    SetupWorkspaceRequest,
)

router = APIRouter(prefix="/setup", tags=["setup"])

VALID_CONNECTION_KINDS = {
    "llm",
    "verifier",
    "apollo",
    "apify",
    "smtp",
    "imap",
}

REQUIRED_CONNECTION_FIELDS = {
    "llm": {"base_url", "api_key", "model_small", "model_large"},
    "verifier": {"provider", "api_key"},
    "apollo": {"api_key"},
    "apify": {"api_token"},
    "smtp": {"host", "port", "username", "password"},
    "imap": {"host", "port", "username", "password"},
}


def _valid_email(email: str) -> bool:
    normalized = normalize_email(email)
    return normalized.count("@") == 1 and "." in normalized.rsplit("@", 1)[1]


async def _first(db, model):
    result = await db.exec(select(model).limit(1))
    return result.first()


@router.get("/status", response_model=SetupStatus)
async def setup_status(db=Depends(get_session)) -> SetupStatus:
    admin = await _first(db, User)
    workspace = await _first(db, Workspace)
    license = await _first(db, LicenseState)

    result = await db.exec(select(Connection))
    connections = result.all()
    connection_kinds = {connection.kind for connection in connections}

    sender_configured = bool(
        workspace
        and workspace.sender_identity
        and workspace.postal_address
    )
    responsibility_accepted = bool(
        workspace and workspace.setup_responsibility_accepted_at is not None
    )
    complete = bool(
        admin
        and workspace
        and workspace.setup_completed_at is not None
        and sender_configured
        and responsibility_accepted
    )
    return SetupStatus(
        initialized=bool(admin and workspace),
        admin_created=admin is not None,
        workspace_created=workspace is not None,
        license_stored=license is not None,
        llm_configured="llm" in connection_kinds,
        verifier_configured="verifier" in connection_kinds,
        sender_configured=sender_configured,
        responsibility_accepted=responsibility_accepted,
        complete=complete,
    )


@router.post("/admin", response_model=SetupAdminResponse)
async def create_initial_admin(
    request: SetupAdminRequest,
    db=Depends(get_session),
) -> SetupAdminResponse:
    existing = await _first(db, User)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been initialized")

    email = normalize_email(request.email)
    if not _valid_email(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid email")

    workspace = Workspace(name=request.workspace_name.strip())
    db.add(workspace)
    await db.flush()

    user = User(
        workspace_id=workspace.id,
        email=email,
        password_hash=hash_password(request.password),
        role="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(workspace)
    await db.refresh(user)

    return SetupAdminResponse(
        workspace_id=workspace.id,
        user_id=user.id,
        email=user.email,
        role=user.role,
    )


@router.post("/workspace")
async def update_workspace(
    request: SetupWorkspaceRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> dict[str, bool]:
    if not request.accept_responsibility:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Responsibility acceptance is required",
        )

    workspace = await db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")

    workspace.name = request.name.strip()
    workspace.sender_identity = request.sender_identity.strip()
    workspace.postal_address = request.postal_address.strip()
    workspace.timezone = request.timezone.strip() or "UTC"
    workspace.setup_responsibility_accepted_at = utcnow()
    workspace.setup_completed_at = utcnow()
    db.add(workspace)
    await db.commit()
    return {"updated": True}


@router.post("/license", response_model=SetupLicenseResponse)
async def store_license(
    request: SetupLicenseRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> SetupLicenseResponse:
    if not settings.LICENSE_PUBLIC_KEY_PEM:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "License public key is not configured")
    try:
        status = verify_license_token(
            request.license_token,
            settings.LICENSE_PUBLIC_KEY_PEM,
        )
    except InvalidLicense as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if not status.valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, status.reason)

    result = await db.exec(
        select(LicenseState).order_by(LicenseState.created_at.desc()).limit(1)
    )
    license = result.first()
    if license is None:
        license = LicenseState(token=request.license_token)
    else:
        license.token = request.license_token
    license.valid_until = status.expires_at
    license.last_checked_at = utcnow()
    db.add(license)
    await db.commit()
    return SetupLicenseResponse(
        stored=True,
        valid=status.valid,
        in_grace=status.in_grace,
        expires_at=status.expires_at,
    )


@router.post("/connection", response_model=SetupConnectionResponse)
async def store_connection(
    request: SetupConnectionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> SetupConnectionResponse:
    kind = request.kind.strip().lower()
    if kind not in VALID_CONNECTION_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown connection kind")

    missing = REQUIRED_CONNECTION_FIELDS[kind] - set(request.secret)
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Missing connection secret fields",
        )

    try:
        encrypted = encrypt_secret(request.secret)
    except ValueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    result = await db.exec(
        select(Connection).where(
            Connection.workspace_id == user.workspace_id,
            Connection.kind == kind,
        ).limit(1)
    )
    connection = result.first()
    if connection is None:
        connection = Connection(
            workspace_id=user.workspace_id,
            kind=kind,
            encrypted_secret=encrypted,
            status="configured",
        )
    else:
        connection.encrypted_secret = encrypted
        connection.status = "configured"
    db.add(connection)
    await db.commit()
    return SetupConnectionResponse(kind=kind, status="configured")


@router.post("/domain", response_model=SetupDomainResponse)
async def store_domain(
    request: SetupDomainRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> SetupDomainResponse:
    name = request.name.strip().lower().rstrip(".")
    if "." not in name or name.startswith("."):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid domain")

    result = await db.exec(
        select(Domain).where(
            Domain.workspace_id == user.workspace_id,
            Domain.name == name,
        ).limit(1)
    )
    domain = result.first()
    if domain is None:
        domain = Domain(workspace_id=user.workspace_id, name=name)
    db.add(domain)
    await db.commit()
    await db.refresh(domain)
    return SetupDomainResponse(
        id=domain.id,
        name=domain.name,
        spf_ok=domain.spf_ok,
        dkim_ok=domain.dkim_ok,
        dmarc_ok=domain.dmarc_ok,
    )


@router.post("/mailbox", response_model=SetupMailboxResponse)
async def store_mailbox(
    request: SetupMailboxRequest,
    user: Annotated[User, Depends(get_current_user)],
    db=Depends(get_session),
) -> SetupMailboxResponse:
    domain = await db.get(Domain, request.domain_id)
    if domain is None or domain.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")

    address = request.address.strip().lower()
    if address.count("@") != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid mailbox")
    if address.rsplit("@", 1)[1] != domain.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mailbox domain mismatch")

    result = await db.exec(
        select(Mailbox).where(
            Mailbox.workspace_id == user.workspace_id,
            Mailbox.address == address,
        ).limit(1)
    )
    mailbox = result.first()
    if mailbox is None:
        if not await check_mailbox_limit(db, user.workspace_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "License mailbox limit reached or license is missing",
            )
        mailbox = Mailbox(
            workspace_id=user.workspace_id,
            domain_id=domain.id,
            address=address,
            daily_cap=request.daily_cap,
            status="warming",
        )
    else:
        mailbox.domain_id = domain.id
        mailbox.daily_cap = request.daily_cap
        mailbox.status = "warming"
    db.add(mailbox)
    await db.commit()
    await db.refresh(mailbox)
    return SetupMailboxResponse(
        id=mailbox.id,
        address=mailbox.address,
        daily_cap=mailbox.daily_cap,
        status=mailbox.status,
    )
