import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.core.websocket import manager
import asyncio

from app.config import settings
from app.core.email import (
    is_smtp_configured,
    is_email_configured,
    send_password_reset_code,
    send_mfa_login_code,
    send_mfa_enabled_confirmation,
)
from app.core.security import (
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.database import get_db
from app.models.password_reset_code import PasswordResetCode
from app.models.mfa_code import MfaCode
from app.core.audit import log_action
from app.models.police_user import PoliceUser
from app.models.user_session import UserSession
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MfaVerifyRequest,
    ResetPasswordRequest,
    Token,
)

MFA_CODE_EXPIRE_MINUTES = 10


router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _authenticate_user(db: Session, email: str, password: str) -> PoliceUser | None:
    user = db.query(PoliceUser).filter(PoliceUser.email == email).first()
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _get_user_from_token(db: Session, token: str) -> PoliceUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        sub: str | None = payload.get("sub")
        if sub is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == int(sub)).first()
    if not user or not user.is_active:
        raise credentials_exception

    # Optional: if sessions table exists, ensure this token corresponds
    # to a non-revoked session. If not found, fall back to accepting
    # the token so legacy tokens still work.
    try:
        session = (
            db.query(UserSession)
            .filter(
                UserSession.police_user_id == user.police_user_id,
                UserSession.refresh_token == token,
                UserSession.expires_at > datetime.now(timezone.utc),
                UserSession.revoked_at.is_(None),
            )
            .first()
        )
    except Exception:
        session = None

    if session is None:
        # Do not immediately revoke access; simply allow login,
        # but admin revoke endpoints will act on sessions when present.
        return user

    return user


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> PoliceUser:
    return _get_user_from_token(db, token)


async def get_optional_user(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: Session = Depends(get_db),
) -> PoliceUser | None:
    """Return current police user if valid token present, else None. Does not raise when token missing."""
    if not token:
        return None
    try:
        return _get_user_from_token(db, token)
    except HTTPException:
        return None


async def get_current_admin(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
) -> PoliceUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def get_current_admin_or_supervisor(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
) -> PoliceUser:
    """Admin, IO (supervisor), and officers — same operational APIs (assign, cases, intel)."""
    if current_user.role not in ("admin", "supervisor", "officer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin, supervisor, or officer access required",
        )
    return current_user


async def get_current_admin_supervisor_or_officer(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
) -> PoliceUser:
    if current_user.role not in ("admin", "supervisor", "officer"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin, supervisor, or officer access required",
        )
    return current_user


async def get_current_admin_or_station_staff(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
) -> PoliceUser:
    """
    Admin: district-wide local leader management.
    Officer / IO: station-scoped local leader management (station_id required).
    """
    if current_user.role == "admin":
        return current_user
    if current_user.role in ("officer", "supervisor"):
        from app.core.station_scope import require_station_id

        require_station_id(current_user)
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin, supervisor, or officer access required",
    )


def _complete_login(user: PoliceUser, db: Session, request: Request, background_tasks: BackgroundTasks) -> Token:
    """Finish login: create session, log action, return token."""
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    access_token = create_access_token(subject=str(user.police_user_id), role=user.role)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    client_ip = request.client.host if hasattr(request, "client") else None
    user_agent_str = request.headers.get("user-agent")
    session_row = UserSession(
        police_user_id=user.police_user_id,
        refresh_token=access_token,
        user_agent=user_agent_str,
        ip_address=client_ip,
        expires_at=expires_at,
    )
    log_action(
        db,
        "user_login",
        actor_type="police_user",
        actor_id=user.police_user_id,
        entity_type="police_user",
        entity_id=str(user.police_user_id),
        action_details={"email": user.email, "role": user.role},
        ip_address=client_ip,
        user_agent=user_agent_str,
        success=True,
    )
    db.add_all([user, session_row])
    db.commit()

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "session"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "session"}))
    background_tasks.add_task(notify)
    return Token(access_token=access_token)


@router.post("/login", response_model=Token)
def login(data: LoginRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    user = _authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    # Check if MFA is enabled for this user
    if getattr(user, "mfa_enabled", False):
        # Generate MFA code and send via email
        code = "".join(secrets.choice("0123456789") for _ in range(6))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=MFA_CODE_EXPIRE_MINUTES)

        # Clear old login codes for this user
        db.query(MfaCode).filter(
            MfaCode.police_user_id == user.police_user_id,
            MfaCode.purpose == "login",
        ).delete()

        mfa_row = MfaCode(
            police_user_id=user.police_user_id,
            code=code,
            purpose="login",
            expires_at=expires_at,
        )
        db.add(mfa_row)
        db.commit()

        # Send email with the code
        user_name = f"{user.first_name} {user.last_name}".strip()
        send_mfa_login_code(user.email, code, user_name)

        # Create a short-lived MFA token (not a full access token)
        mfa_token = create_access_token(
            subject=str(user.police_user_id),
            role="mfa_pending",
            expires_delta=timedelta(minutes=MFA_CODE_EXPIRE_MINUTES),
        )

        return Token(
            access_token="",
            mfa_required=True,
            mfa_token=mfa_token,
        )

    # No MFA — complete login directly
    return _complete_login(user, db, request, background_tasks)


@router.get("/me", response_model=MeResponse)
def me(current_user: Annotated[PoliceUser, Depends(get_current_user)]):
    return current_user


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Change the current user's password. Any authenticated user."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    current_user.password_hash = get_password_hash(payload.new_password)
    current_user.last_password_change = datetime.now(timezone.utc)
    db.add(current_user)
    db.commit()

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "user"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "user"}))
    background_tasks.add_task(notify)

    return {"message": "Password updated"}


@router.post("/revoke-other-sessions")
def revoke_other_sessions(
    token: Annotated[str, Depends(oauth2_scheme)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """
    Revoke all other active sessions for the current user, keeping this one.
    """
    now = datetime.now(timezone.utc)
    (
        db.query(UserSession)
        .filter(
            UserSession.police_user_id == current_user.police_user_id,
            UserSession.refresh_token != token,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .update({UserSession.revoked_at: now}, synchronize_session=False)
    )
    db.commit()

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "session"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "session"}))
    background_tasks.add_task(notify)

    return {"message": "Other sessions revoked"}


@router.post("/verify-mfa", response_model=Token)
def verify_mfa(
    data: MfaVerifyRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """Verify the MFA code sent to the user's email during login."""
    # Decode the mfa_token to get the user
    try:
        payload = jwt.decode(data.mfa_token, settings.secret_key, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        if not user_id or role != "mfa_pending":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired MFA token")

    user = db.query(PoliceUser).filter(PoliceUser.police_user_id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Verify the code
    code_row = (
        db.query(MfaCode)
        .filter(
            MfaCode.police_user_id == user.police_user_id,
            MfaCode.purpose == "login",
            MfaCode.code == data.code.strip(),
            MfaCode.expires_at > datetime.now(timezone.utc),
            MfaCode.used_at.is_(None),
        )
        .first()
    )
    if not code_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    # Mark code as used
    code_row.used_at = datetime.now(timezone.utc)
    db.add(code_row)

    # Complete the login
    return _complete_login(user, db, request, background_tasks)


@router.post("/enable-2fa")
def enable_2fa(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Send a verification code to the user's email to enable 2FA."""
    if getattr(current_user, "mfa_enabled", False):
        return {"message": "Two-factor authentication is already enabled."}

    if not is_email_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email is not configured. Contact an administrator.",
        )

    # Generate and store verification code
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MFA_CODE_EXPIRE_MINUTES)

    db.query(MfaCode).filter(
        MfaCode.police_user_id == current_user.police_user_id,
        MfaCode.purpose == "enable",
    ).delete()

    mfa_row = MfaCode(
        police_user_id=current_user.police_user_id,
        code=code,
        purpose="enable",
        expires_at=expires_at,
    )
    db.add(mfa_row)
    db.commit()

    user_name = f"{current_user.first_name} {current_user.last_name}".strip()
    send_mfa_login_code(current_user.email, code, user_name)

    return {"message": "Verification code sent to your email."}


@router.post("/confirm-enable-2fa")
def confirm_enable_2fa(
    payload: MfaVerifyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Confirm the verification code to enable 2FA."""
    code_row = (
        db.query(MfaCode)
        .filter(
            MfaCode.police_user_id == current_user.police_user_id,
            MfaCode.purpose == "enable",
            MfaCode.code == payload.code.strip(),
            MfaCode.expires_at > datetime.now(timezone.utc),
            MfaCode.used_at.is_(None),
        )
        .first()
    )
    if not code_row:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    code_row.used_at = datetime.now(timezone.utc)
    current_user.mfa_enabled = True
    current_user.mfa_method = "email"
    db.add_all([code_row, current_user])
    db.commit()

    user_name = f"{current_user.first_name} {current_user.last_name}".strip()
    send_mfa_enabled_confirmation(current_user.email, user_name)

    return {"message": "Two-factor authentication has been enabled."}


@router.post("/disable-2fa")
def disable_2fa(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
):
    """Disable 2FA. Requires current password for security."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect password")

    current_user.mfa_enabled = False
    db.add(current_user)
    db.commit()

    return {"message": "Two-factor authentication has been disabled."}


RESET_CODE_EXPIRE_MINUTES = 15


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Request a password reset. If the email belongs to an active user and SMTP is configured,
    sends a 6-digit code to that email. Always returns 200 to avoid leaking account existence.
    """
    email = payload.email.strip().lower()
    user = db.query(PoliceUser).filter(PoliceUser.email == email, PoliceUser.is_active.is_(True)).first()
    if not user:
        return {"message": "If an account exists with this email, you will receive a verification code shortly."}

    if not is_smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email is not configured (Brevo or SMTP). Contact an administrator to reset your password.",
        )

    # Invalidate any existing codes for this email
    db.query(PasswordResetCode).filter(PasswordResetCode.email == email).delete()

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_CODE_EXPIRE_MINUTES)
    row = PasswordResetCode(email=email, code=code, expires_at=expires_at)
    db.add(row)
    db.commit()

    ok, err = send_password_reset_code(email, code)
    if not ok:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=err or "Failed to send email.",
        )

    return {"message": "If an account exists with this email, you will receive a verification code shortly."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using the code sent to the user's email."""
    email = payload.email.strip().lower()
    code = payload.code.strip()

    row = (
        db.query(PasswordResetCode)
        .filter(
            PasswordResetCode.email == email,
            PasswordResetCode.code == code,
            PasswordResetCode.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code. Please request a new code.",
        )

    user = db.query(PoliceUser).filter(PoliceUser.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code.")

    user.password_hash = get_password_hash(payload.new_password)
    db.add(user)
    db.delete(row)
    db.commit()

    return {"message": "Password has been reset. You can now log in with your new password."}

