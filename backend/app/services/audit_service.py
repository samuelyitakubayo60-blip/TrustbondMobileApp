"""
Enhanced audit service with role-based access and data masking
"""
import json
import re
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog
from app.models.police_user import PoliceUser


class AuditService:
    """Enhanced audit logging with security and role identification"""
    
    @staticmethod
    def log_action(
        db: Session,
        actor_type: str,
        actor_id: Optional[int],
        action_type: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        action_details: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        sensitivity_level: str = "low"
    ):
        """Log an action with automatic role detection and data masking"""
        
        # Get actor role if police_user
        actor_role = None
        if actor_type == "police_user" and actor_id:
            user = db.query(PoliceUser).filter(PoliceUser.police_user_id == actor_id).first()
            actor_role = user.role if user else None
        
        # Create masked version of details
        masked_details = AuditService._mask_sensitive_data(action_details, sensitivity_level, actor_role)
        
        audit_log = AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            actor_role=actor_role,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            action_details=action_details,
            masked_details=masked_details,
            sensitivity_level=sensitivity_level,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success
        )
        
        db.add(audit_log)
        db.commit()
    
    @staticmethod
    def _mask_sensitive_data(data: Dict[str, Any], sensitivity_level: str, viewer_role: Optional[str]) -> Dict[str, Any]:
        """Mask sensitive data based on sensitivity level and viewer role"""
        if not data:
            return {}
        
        masked = data.copy()
        
        # Admins see everything
        if viewer_role == "admin":
            return masked
        
        # Define sensitive fields
        sensitive_fields = {
            "phone_number": lambda x: AuditService._mask_phone(x),
            "email": lambda x: AuditService._mask_email(x),
            "full_name": lambda x: AuditService._mask_name(x),
            "address": lambda x: AuditService._mask_address(x),
            "description": lambda x: AuditService._mask_description(x, sensitivity_level),
            "latitude": lambda x: AuditService._mask_coordinates(x),
            "longitude": lambda x: AuditService._mask_coordinates(x),
        }
        
        # Apply masking based on sensitivity level
        for field, mask_func in sensitive_fields.items():
            if field in masked:
                if sensitivity_level == "high":
                    # Always mask high sensitivity
                    masked[field] = mask_func(masked[field])
                elif sensitivity_level == "medium":
                    # Mask medium sensitivity for non-admins
                    if viewer_role not in ["admin", "supervisor"]:
                        masked[field] = mask_func(masked[field])
                elif field in ["phone_number", "email"]:
                    # Always mask PII even for low sensitivity
                    masked[field] = mask_func(masked[field])
        
        return masked
    
    @staticmethod
    def _mask_phone(phone: str) -> str:
        """Mask phone number: +250788123456 -> +250***456"""
        if not phone or len(phone) < 6:
            return "***"
        return phone[:4] + "***" + phone[-3:]
    
    @staticmethod
    def _mask_email(email: str) -> str:
        """Mask email: john.doe@email.com -> j***@email.com"""
        if not email or "@" not in email:
            return "***@***.com"
        local, domain = email.split("@", 1)
        return local[0] + "***@" + domain
    
    @staticmethod
    def _mask_name(name: str) -> str:
        """Mask name: John Doe -> J*** D***"""
        if not name:
            return "***"
        parts = name.split()
        masked_parts = [part[0] + "***" if len(part) > 1 else part for part in parts]
        return " ".join(masked_parts)
    
    @staticmethod
    def _mask_address(address: str) -> str:
        """Mask address: 123 Main St -> *** Main St"""
        if not address:
            return "***"
        # Keep street name but mask number
        parts = address.split()
        if parts and parts[0].isdigit():
            parts[0] = "***"
        return " ".join(parts)
    
    @staticmethod
    def _mask_description(description: str, sensitivity_level: str) -> str:
        """Mask description based on sensitivity"""
        if not description:
            return ""
        
        if sensitivity_level == "high":
            # Completely mask high sensitivity descriptions
            return "[Content masked due to high sensitivity]"
        elif sensitivity_level == "medium":
            # Truncate medium sensitivity descriptions
            if len(description) > 50:
                return description[:50] + "..."
            return description
        
        return description
    
    @staticmethod
    def _mask_coordinates(coord) -> str:
        """Mask coordinates to sector level"""
        if not coord:
            return "***"
        return "***"  # Completely mask coordinates for non-admins
    
    @staticmethod
    def get_audit_logs(
        db: Session,
        current_user: PoliceUser,
        skip: int = 0,
        limit: int = 100,
        entity_type: Optional[str] = None,
        action_type: Optional[str] = None
    ) -> list:
        """Get audit logs with role-based filtering"""
        
        query = db.query(AuditLog)
        
        # Apply filters
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if action_type:
            query = query.filter(AuditLog.action_type == action_type)
        
        # Role-based filtering
        if current_user.role == "officer":
            # Officers only see their own actions
            query = query.filter(
                (AuditLog.actor_type == "system") |
                (AuditLog.actor_id == current_user.police_user_id)
            )
        elif current_user.role == "supervisor":
            # Supervisors see system actions and their station's actions
            if current_user.station_id:
                query = query.filter(
                    (AuditLog.actor_type == "system") |
                    (AuditLog.actor_id.in_(
                        db.query(PoliceUser.police_user_id)
                        .filter(PoliceUser.station_id == current_user.station_id)
                    ))
                )
        
        # Order and paginate
        logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
        
        # Return appropriate details based on user role
        result = []
        for log in logs:
            log_data = {
                "log_id": log.log_id,
                "actor_type": log.actor_type,
                "actor_id": log.actor_id,
                "actor_role": log.actor_role,
                "action_type": log.action_type,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "sensitivity_level": log.sensitivity_level,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "success": log.success,
                "created_at": log.created_at
            }
            
            # Choose appropriate details based on user role
            if current_user.role == "admin":
                log_data["details"] = log.action_details
            else:
                log_data["details"] = log.masked_details or log.action_details
            
            result.append(log_data)
        
        return result
