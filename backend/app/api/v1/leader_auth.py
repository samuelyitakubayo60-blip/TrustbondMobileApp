import secrets
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, verify_password
from app.core.email import is_smtp_configured, send_leader_otp_email
from app.database import get_db
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.models.local_leader_auth_code import LocalLeaderAuthCode
from app.schemas.local_leader import (
    LocalLeaderLoginRequest,
    LocalLeaderMeResponse,
    LocalLeaderToken,
    LocalLeaderRequestCodeRequest,
    LocalLeaderSetPasswordRequest,
    LocalLeaderVerifyLoginCodeRequest,
    LocalLeaderFcmTokenRequest,
)
from app.core.security import get_password_hash


router = APIRouter(prefix="/leader-auth", tags=["leader-auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/leader-auth/login")
optional_leader_bearer = HTTPBearer(auto_error=False)


def _norm_email(value: str) -> str:
    return (value or "").strip().lower()


def _authenticate_local_leader(db: Session, email: str, password: str) -> LocalLeader | None:
    em = _norm_email(email)
    if not em:
        return None
    leader = db.query(LocalLeader).filter(func.lower(LocalLeader.email) == em).first()
    if not leader or not leader.is_active:
        return None
    if not verify_password(password, leader.password_hash):
        return None
    return leader


def _get_local_leader_from_token(db: Session, token: str) -> LocalLeader:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        sub: str | None = payload.get("sub")
        tok_role: str | None = payload.get("role")
        if sub is None or tok_role != "local_leader":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    if not sub.startswith("ll:"):
        raise credentials_exception
    leader_id = int(sub.split("ll:", 1)[1])
    leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == leader_id).first()
    if not leader or not leader.is_active:
        raise credentials_exception
    return leader


def get_current_local_leader(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> LocalLeader:
    return _get_local_leader_from_token(db, token)


def get_optional_local_leader(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(optional_leader_bearer)],
    db: Session = Depends(get_db),
) -> LocalLeader | None:
    if not credentials or not (credentials.credentials or "").strip():
        return None
    try:
        return _get_local_leader_from_token(db, credentials.credentials.strip())
    except HTTPException:
        return None


@router.post("/login", response_model=LocalLeaderToken)
def login(payload: LocalLeaderLoginRequest, db: Session = Depends(get_db)):
    leader = _authenticate_local_leader(db, payload.email, payload.password)
    if not leader:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    now = datetime.now(timezone.utc)
    leader.last_login_at = now
    access_token = create_access_token(subject=f"ll:{leader.local_leader_id}", role="local_leader")

    db.add(leader)
    db.commit()

    return LocalLeaderToken(access_token=access_token)


@router.post("/register-fcm-token")
def register_fcm_token(
    payload: LocalLeaderFcmTokenRequest,
    db: Session = Depends(get_db),
    current_leader: Annotated[LocalLeader, Depends(get_current_local_leader)] = None,
):
    tok = (payload.fcm_token or "").strip()
    if len(tok) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid FCM token")
    current_leader.fcm_device_token = tok[:512]
    db.add(current_leader)
    db.commit()
    return {"message": "OK"}


@router.get("/me", response_model=LocalLeaderMeResponse)
def me(
    db: Session = Depends(get_db),
    current_leader: Annotated[LocalLeader, Depends(get_current_local_leader)] = None,
):
    covered_location_ids = [
        int(r[0])
        for r in db.query(LocalLeaderCoverageLocation.location_id)
        .filter(LocalLeaderCoverageLocation.local_leader_id == current_leader.local_leader_id)
        .all()
    ]
    return LocalLeaderMeResponse(
        local_leader_id=current_leader.local_leader_id,
        full_name=current_leader.full_name,
        role=current_leader.role,
        phone_number=current_leader.phone_number,
        email=current_leader.email,
        covered_location_ids=covered_location_ids,
    )


CODE_EXPIRE_MINUTES = 10
LOGIN_CODE_RESEND_COOLDOWN_SECONDS = 30


@router.post("/request-setup-code")
def request_setup_code(payload: LocalLeaderRequestCodeRequest, db: Session = Depends(get_db)):
    em = _norm_email(payload.email)
    leader = db.query(LocalLeader).filter(func.lower(LocalLeader.email) == em, LocalLeader.is_active.is_(True)).first()
    if not leader or not leader.email:
        return {"message": "If this email is registered, a setup code was sent."}

    if not is_smtp_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured on the server.")

    db.query(LocalLeaderAuthCode).filter(
        LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
        LocalLeaderAuthCode.purpose == "password_setup",
        LocalLeaderAuthCode.used_at.is_(None),
    ).delete()

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRE_MINUTES)
    row = LocalLeaderAuthCode(
        local_leader_id=leader.local_leader_id,
        phone_number=None,
        code=code,
        purpose="password_setup",
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()

    ok, err = send_leader_otp_email(leader.email, code, "password_setup")
    if not ok:
        raise HTTPException(status_code=503, detail=err or "Failed to send setup email.")
    return {"message": "If this email is registered, a setup code was sent."}


@router.post("/set-password")
def set_password(payload: LocalLeaderSetPasswordRequest, db: Session = Depends(get_db)):
    em = _norm_email(payload.email)
    code = (payload.code or "").strip()
    leader = db.query(LocalLeader).filter(func.lower(LocalLeader.email) == em, LocalLeader.is_active.is_(True)).first()
    if not leader:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    row = (
        db.query(LocalLeaderAuthCode)
        .filter(
            LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
            LocalLeaderAuthCode.code == code,
            LocalLeaderAuthCode.purpose == "password_setup",
            LocalLeaderAuthCode.expires_at > datetime.now(timezone.utc),
            LocalLeaderAuthCode.used_at.is_(None),
        )
        .order_by(LocalLeaderAuthCode.local_leader_auth_code_id.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    leader.password_hash = get_password_hash(payload.new_password)
    row.used_at = datetime.now(timezone.utc)
    db.add_all([leader, row])
    db.commit()
    return {"message": "Password updated successfully. You can now log in."}


@router.post("/request-login-code")
def request_login_code(payload: LocalLeaderRequestCodeRequest, db: Session = Depends(get_db)):
    em = _norm_email(payload.email)
    leader = db.query(LocalLeader).filter(func.lower(LocalLeader.email) == em, LocalLeader.is_active.is_(True)).first()
    if not leader or not leader.email:
        return {"message": "If this email is registered, a login code was sent."}

    if not is_smtp_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured on the server.")

    latest = (
        db.query(LocalLeaderAuthCode)
        .filter(
            LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
            LocalLeaderAuthCode.purpose == "login_otp",
        )
        .order_by(LocalLeaderAuthCode.local_leader_auth_code_id.desc())
        .first()
    )
    if latest and latest.created_at:
        elapsed = (datetime.now(timezone.utc) - latest.created_at).total_seconds()
        if elapsed < LOGIN_CODE_RESEND_COOLDOWN_SECONDS:
            retry_after = int(LOGIN_CODE_RESEND_COOLDOWN_SECONDS - elapsed)
            return {
                "message": "OTP recently sent. Please wait before requesting again.",
                "retry_after_seconds": max(1, retry_after),
            }

    db.query(LocalLeaderAuthCode).filter(
        LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
        LocalLeaderAuthCode.purpose == "login_otp",
        LocalLeaderAuthCode.used_at.is_(None),
    ).delete()

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    row = LocalLeaderAuthCode(
        local_leader_id=leader.local_leader_id,
        phone_number=None,
        code=code,
        purpose="login_otp",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRE_MINUTES),
    )
    db.add(row)
    db.commit()

    ok, err = send_leader_otp_email(leader.email, code, "login_otp")
    if not ok:
        raise HTTPException(status_code=503, detail=err or "Failed to send login email.")
    return {
        "message": "If this email is registered, a login code was sent.",
        "retry_after_seconds": LOGIN_CODE_RESEND_COOLDOWN_SECONDS,
    }


@router.post("/verify-login-code", response_model=LocalLeaderToken)
def verify_login_code(payload: LocalLeaderVerifyLoginCodeRequest, db: Session = Depends(get_db)):
    em = _norm_email(payload.email)
    code = (payload.code or "").strip()
    leader = db.query(LocalLeader).filter(func.lower(LocalLeader.email) == em, LocalLeader.is_active.is_(True)).first()
    if not leader:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    row = (
        db.query(LocalLeaderAuthCode)
        .filter(
            LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
            LocalLeaderAuthCode.code == code,
            LocalLeaderAuthCode.purpose == "login_otp",
            LocalLeaderAuthCode.expires_at > datetime.now(timezone.utc),
            LocalLeaderAuthCode.used_at.is_(None),
        )
        .order_by(LocalLeaderAuthCode.local_leader_auth_code_id.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    row.used_at = datetime.now(timezone.utc)
    leader.last_login_at = datetime.now(timezone.utc)
    access_token = create_access_token(subject=f"ll:{leader.local_leader_id}", role="local_leader")
    db.add_all([row, leader])
    db.commit()
    return LocalLeaderToken(access_token=access_token)
