import secrets
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, verify_password
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
)
from app.core.security import get_password_hash
from app.core.sms import send_esms_sms


router = APIRouter(prefix="/leader-auth", tags=["leader-auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/leader-auth/login")


def _authenticate_local_leader(db: Session, phone_number: str, password: str) -> LocalLeader | None:
    phone = (phone_number or "").strip()
    if not phone:
        return None
    leader = db.query(LocalLeader).filter(LocalLeader.phone_number == phone).first()
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
        role: str | None = payload.get("role")
        if sub is None or role != "local_leader":
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


@router.post("/login", response_model=LocalLeaderToken)
def login(payload: LocalLeaderLoginRequest, request: Request, db: Session = Depends(get_db)):
    leader = _authenticate_local_leader(db, payload.phone_number, payload.password)
    if not leader:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect phone number or password")

    now = datetime.now(timezone.utc)
    leader.last_login_at = now
    access_token = create_access_token(subject=f"ll:{leader.local_leader_id}", role="local_leader")

    db.add(leader)
    db.commit()

    return LocalLeaderToken(access_token=access_token)


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
        phone_number=current_leader.phone_number,
        email=current_leader.email,
        covered_location_ids=covered_location_ids,
    )


CODE_EXPIRE_MINUTES = 10
LOGIN_CODE_RESEND_COOLDOWN_SECONDS = 30


@router.post("/request-setup-code")
def request_setup_code(payload: LocalLeaderRequestCodeRequest, db: Session = Depends(get_db)):
    phone = (payload.phone_number or "").strip()
    leader = db.query(LocalLeader).filter(LocalLeader.phone_number == phone, LocalLeader.is_active.is_(True)).first()
    # Always return generic success to avoid account probing.
    if not leader:
        return {"message": "If this number is registered, a setup code was generated."}

    db.query(LocalLeaderAuthCode).filter(
        LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
        LocalLeaderAuthCode.purpose == "password_setup",
        LocalLeaderAuthCode.used_at.is_(None),
    ).delete()

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRE_MINUTES)
    row = LocalLeaderAuthCode(
        local_leader_id=leader.local_leader_id,
        phone_number=phone,
        code=code,
        purpose="password_setup",
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()

    ok, err = send_esms_sms(
        phone,
        f"TrustBond setup code: {code}. Expires in {CODE_EXPIRE_MINUTES} minutes.",
    )
    if not ok:
        raise HTTPException(status_code=503, detail=err or "Failed to send setup code SMS.")
    return {"message": "If this number is registered, a setup code was generated."}


@router.post("/set-password")
def set_password(payload: LocalLeaderSetPasswordRequest, db: Session = Depends(get_db)):
    phone = (payload.phone_number or "").strip()
    code = (payload.code or "").strip()
    row = (
        db.query(LocalLeaderAuthCode)
        .filter(
            LocalLeaderAuthCode.phone_number == phone,
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

    leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == row.local_leader_id).first()
    if not leader or not leader.is_active:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    leader.password_hash = get_password_hash(payload.new_password)
    row.used_at = datetime.now(timezone.utc)
    db.add_all([leader, row])
    db.commit()
    return {"message": "Password updated successfully. You can now log in."}


@router.post("/request-login-code")
def request_login_code(payload: LocalLeaderRequestCodeRequest, db: Session = Depends(get_db)):
    phone = (payload.phone_number or "").strip()
    leader = db.query(LocalLeader).filter(LocalLeader.phone_number == phone, LocalLeader.is_active.is_(True)).first()
    # Generic response to prevent account probing.
    if not leader:
        return {"message": "If this number is registered, a login code was generated."}

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
        phone_number=phone,
        code=code,
        purpose="login_otp",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRE_MINUTES),
    )
    db.add(row)
    db.commit()

    ok, err = send_esms_sms(
        phone,
        f"TrustBond login OTP: {code}. Expires in {CODE_EXPIRE_MINUTES} minutes.",
    )
    if not ok:
        raise HTTPException(status_code=503, detail=err or "Failed to send login OTP SMS.")
    return {"message": "If this number is registered, a login code was generated.", "retry_after_seconds": LOGIN_CODE_RESEND_COOLDOWN_SECONDS}


@router.post("/verify-login-code", response_model=LocalLeaderToken)
def verify_login_code(payload: LocalLeaderVerifyLoginCodeRequest, db: Session = Depends(get_db)):
    phone = (payload.phone_number or "").strip()
    code = (payload.code or "").strip()
    row = (
        db.query(LocalLeaderAuthCode)
        .filter(
            LocalLeaderAuthCode.phone_number == phone,
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

    leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == row.local_leader_id).first()
    if not leader or not leader.is_active:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    row.used_at = datetime.now(timezone.utc)
    leader.last_login_at = datetime.now(timezone.utc)
    access_token = create_access_token(subject=f"ll:{leader.local_leader_id}", role="local_leader")
    db.add_all([row, leader])
    db.commit()
    return LocalLeaderToken(access_token=access_token)

