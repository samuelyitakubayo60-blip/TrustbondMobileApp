from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from app.database import Base


class LocalLeader(Base):
    __tablename__ = "local_leaders"

    local_leader_id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(200), nullable=False)
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True))

