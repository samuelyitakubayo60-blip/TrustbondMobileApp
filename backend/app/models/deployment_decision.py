from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class DeploymentDecision(Base):
    __tablename__ = "deployment_decisions"

    decision_id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(36), ForeignKey("reports.report_id"), nullable=False)
    case_id = Column(String(36), ForeignKey("cases.case_id"), nullable=True)
    
    # Who made the decision (station commander/supervisor)
    decided_by = Column(Integer, ForeignKey("police_users.police_user_id"), nullable=False)
    
    # Decision details
    deployment_status = Column(String(20), default="pending")  # pending, deployed, declined, monitoring
    assigned_unit = Column(String(80))  # quick_response, counter_terror, fire_rescue, general_patrol
    deployment_priority = Column(String(20), default="medium")  # low, medium, high, urgent
    
    # Decision reasoning
    decision_note = Column(Text)
    leader_confirmation_weight = Column(Integer, default=0)  # 1-5 scale of how much leader confirmation influenced decision
    
    # Deployment tracking
    deployed_at = Column(DateTime(timezone=True))
    estimated_arrival = Column(DateTime(timezone=True))
    actual_arrival = Column(DateTime(timezone=True))
    
    # Outcome tracking
    deployment_outcome = Column(String(50))  # successful, partial, false_alarm, escalated
    outcome_note = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    report = relationship("Report", backref="deployment_decisions")
    case = relationship("Case", backref="deployment_decisions")
    decided_by_user = relationship("PoliceUser", foreign_keys=[decided_by])


class SuspectVictimTracking(Base):
    __tablename__ = "suspect_victim_tracking"

    tracking_id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(36), ForeignKey("cases.case_id"), nullable=False)
    
    # Person details
    person_type = Column(String(20), nullable=False)  # suspect, victim, witness
    full_name = Column(String(200), nullable=False)
    national_id = Column(String(30), nullable=True)
    phone_number = Column(String(20), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String(10), nullable=True)
    
    # Status tracking
    status = Column(String(30), default="identified")  # identified, detained, released, hospitalized, handed_to_rib
    status_note = Column(Text)
    
    # RIB handover specifics
    rib_case_number = Column(String(50), nullable=True)
    rib_handover_date = Column(DateTime(timezone=True), nullable=True)
    rib_officer_name = Column(String(200), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    case = relationship("Case", backref="suspect_victim_tracking")
