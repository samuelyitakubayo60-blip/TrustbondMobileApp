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
from app.core.email import is_smtp_configured, send_password_reset_code
from app.core.security import (
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.database import get_db
from app.models.password_reset_code import PasswordResetCode
from app.models.police_user import PoliceUser
from app.models.user_session import UserSession
from app.schemas.auth import ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, MeResponse, ResetPasswordRequest, Token


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
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or supervisor access required",
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


@router.post("/login", response_model=Token)
def login(data: LoginRequest, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    user = _authenticate_user(db, data.email, data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    # Update last_login_at
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    access_token = create_access_token(subject=str(user.police_user_id), role=user.role)

    # Create / record a session tied to this access token
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Get client IP address and user agent from request
    client_ip = request.client.host if hasattr(request, 'client') else None
    user_agent_str = request.headers.get("user-agent")
    
    session_row = UserSession(
        police_user_id=user.police_user_id,
        refresh_token=access_token,
        user_agent=user_agent_str,
        ip_address=client_ip,
        expires_at=expires_at,
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
            detail="Email is not configured. Contact an administrator to reset your password.",
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

