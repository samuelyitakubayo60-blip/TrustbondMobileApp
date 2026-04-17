"""
Email notification service for sending email alerts to police users.
Integrates with existing notification system to send both web and email notifications.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from datetime import datetime
import logging

from sqlalchemy.orm import Session, joinedload
from app.models.police_user import PoliceUser
from app.models.location import Location
from app.database import SessionLocal


def get_location_hierarchy_from_coordinates(db: Session, latitude: float, longitude: float) -> str:
    """
    Convert coordinates to location hierarchy (sector, cell, village).
    
    Args:
        db: Database session
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        
    Returns:
        Location hierarchy string (e.g., "Sector, Cell, Village") or coordinates if no location found
    """
    try:
        from app.core.village_lookup import get_village_location_info
        
        # Get village location info using the proper lookup service
        location_info = get_village_location_info(db, latitude, longitude)
        
        if location_info:
            # Build location hierarchy in order: Sector, Cell, Village
            location_parts = []
            
            # Add sector if available
            if location_info.get("sector_name"):
                location_parts.append(location_info["sector_name"])
            
            # Add cell if available
            if location_info.get("cell_name"):
                location_parts.append(location_info["cell_name"])
            
            # Add village if available
            if location_info.get("village_name"):
                location_parts.append(location_info["village_name"])
            
            if location_parts:
                return ", ".join(location_parts)
        
        # Fallback to coordinates if no location found
        return f"{float(latitude):.4f}, {float(longitude):.4f}"
        
    except Exception as e:
        logger.error(f"Error getting location hierarchy: {e}")
        return f"{float(latitude):.4f}, {float(longitude):.4f}"


def generate_google_maps_link(latitude: float, longitude: float, address: str = None) -> dict:
    """
    Generate Google Maps links for navigation and viewing.
    
    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate  
        address: Optional address description
        
    Returns:
        Dictionary with different Google Maps URLs
    """
    lat, lon = float(latitude), float(longitude)
    
    # Google Maps navigation link (for driving directions)
    navigation_url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
    
    # Google Maps view link (to see the location on map)
    view_url = f"https://www.google.com/maps?q={lat},{lon}"
    
    # Google Maps search link (if address is available)
    search_url = f"https://www.google.com/maps/search/?api=1&query={address}" if address else view_url
    
    return {
        "navigation": navigation_url,
        "view": view_url, 
        "search": search_url,
        "coordinates": f"{lat},{lon}"
    }

logger = logging.getLogger(__name__)


class EmailNotificationService:
    """Service for sending email notifications to police users."""
    
    def __init__(self):
        # Load environment variables if not already loaded
        from dotenv import load_dotenv
        load_dotenv()
        
        self.smtp_server = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASS", "")
        self.from_email = os.getenv("SMTP_FROM", "noreply@trustbond.system")
        self.frontend_url = os.getenv("VITE_API_BASE_URL", "https://trustbondmobileapp.onrender.com")
        
        # Check if email is configured
        self.email_enabled = bool(self.smtp_username and self.smtp_password)
        
        if not self.email_enabled:
            logger.warning("Email notifications disabled - SMTP credentials not configured")
    
    def send_email(
        self,
        to_emails: List[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        """
        Send email to specified recipients.
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_body: HTML email body
            text_body: Plain text email body (optional)
            
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.email_enabled:
            logger.warning("Email not configured - skipping email send")
            return False
        
        if not to_emails:
            logger.warning("No recipients specified - skipping email send")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = ', '.join(to_emails)
            
            # Add plain text body
            if text_body:
                text_part = MIMEText(text_body, 'plain')
                msg.attach(text_part)
            
            # Add HTML body
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {len(to_emails)} recipients")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False
    
    def send_case_assignment_notification(
        self,
        police_user: PoliceUser,
        case_number: str,
        case_title: str,
        incident_type: str,
        location: str,
        report_count: int,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> bool:
        """
        Send email notification when a case is assigned to an officer.
        
        Args:
            police_user: The police user assigned to the case
            case_number: Case number
            case_title: Case title
            incident_type: Type of incident
            location: Case location
            report_count: Number of reports in the case
            
        Returns:
            True if email sent successfully, False otherwise
        """
        if not police_user.email:
            logger.warning(f"Police user {police_user.police_user_id} has no email address")
            return False
        
        subject = f"New Case Assigned: {case_number}"
        
        case_url = f"{self.frontend_url}/cases/{case_number}"
        
        # Build display + one unified case-level maps link.
        # Handle both coordinate strings (lat, lon) and location descriptions
        location_display = location
        maps_links = None

        if latitude is not None and longitude is not None:
            try:
                lat_f = float(latitude)
                lon_f = float(longitude)
                maps_links = generate_google_maps_link(lat_f, lon_f)
            except (TypeError, ValueError):
                maps_links = None
        
        if ',' in location and location.replace(',', '').replace('.', '').replace(' ', '').replace('-', '').isdigit():
            # This looks like coordinates, convert to location hierarchy
            try:
                lat, lon = float(location.split(',')[0]), float(location.split(',')[1])
                db = SessionLocal()
                try:
                    location_display = get_location_hierarchy_from_coordinates(db, lat, lon)
                    if maps_links is None:
                        maps_links = generate_google_maps_link(lat, lon)
                finally:
                    db.close()
            except (ValueError, IndexError):
                pass
        
        html_body = f"""
        <html>
        <body>
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #2563eb; color: white; padding: 20px; text-align: center;">
                    <h1>TrustBond System</h1>
                    <h2>New Case Assignment</h2>
                </div>
                
                <div style="padding: 20px; background-color: #f8f9fa;">
                    <p>Dear {f"{police_user.first_name} {police_user.last_name}".strip() or police_user.email},</p>
                    
                    <p>A new case has been assigned to you:</p>
                    
                    <div style="background-color: white; padding: 15px; border-left: 4px solid #2563eb; margin: 15px 0;">
                        <h3>{case_number}</h3>
                        <p><strong>Title:</strong> {case_title}</p>
                        <p><strong>Incident Type:</strong> {incident_type}</p>
                        <p><strong>Location:</strong> {location_display}</p>
                        <p><strong>Reports:</strong> {report_count}</p>
                    </div>
                    
                    <p>Please review the case details and take appropriate action.</p>
                    
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{case_url}" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            View Case Details
                        </a>
                        {f'<a href="{maps_links["navigation"]}" style="background-color: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">🚗 Navigate to Case Area</a>' if maps_links else ''}
                    </div>
                    
                    {f'<div style="background-color: #e3f2fd; padding: 10px; border-radius: 4px; margin: 15px 0;"><p style="margin: 0; font-size: 14px;"><strong>📍 Quick Navigation:</strong> <a href="{maps_links["view"]}" style="color: #1976d2; text-decoration: none;">View on Map</a> | <a href="{maps_links["navigation"]}" style="color: #1976d2; text-decoration: none;">Get Directions</a></p></div>' if maps_links else ''}
                    
                    <p style="font-size: 12px; color: #666; margin-top: 20px;">
                        This is an automated notification from the TrustBond system. 
                        If you have questions, please contact your supervisor.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        New Case Assigned: {case_number}
        
        Title: {case_title}
        Incident Type: {incident_type}
        Location: {location_display}
        Reports: {report_count}
        
        Please review the case details at: {case_url}
        {f'Navigate to case area: {maps_links["navigation"]}' if maps_links else ''}
        
        This is an automated notification from the TrustBond system.
        """
        
        return self.send_email([police_user.email], subject, html_body, text_body)
    
    def send_auto_case_notification(
        self,
        police_users: List[PoliceUser],
        case_number: str,
        case_title: str,
        incident_type: str,
        location: str,
        report_count: int,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> int:
        """
        Send email notification to multiple users when a case is auto-created.
        
        Args:
            police_users: List of police users to notify
            case_number: Case number
            case_title: Case title
            incident_type: Type of incident
            location: Case location
            report_count: Number of reports in the case
            
        Returns:
            Number of successful email sends
        """
        successful_sends = 0
        
        # Filter users with email addresses
        users_with_email = [user for user in police_users if user.email]
        
        if not users_with_email:
            logger.warning("No police users with email addresses found")
            return 0
        
        subject = f"Auto-Generated Case: {case_number}"
        
        case_url = f"{self.frontend_url}/cases/{case_number}"
        
        # Build display + one unified case-level maps link.
        location_display = location
        maps_links = None

        if latitude is not None and longitude is not None:
            try:
                lat_f = float(latitude)
                lon_f = float(longitude)
                maps_links = generate_google_maps_link(lat_f, lon_f)
            except (TypeError, ValueError):
                maps_links = None
        
        if ',' in location and location.replace(',', '').replace('.', '').replace(' ', '').replace('-', '').isdigit():
            # This looks like coordinates, convert to location hierarchy
            try:
                lat, lon = float(location.split(',')[0]), float(location.split(',')[1])
                db = SessionLocal()
                try:
                    location_display = get_location_hierarchy_from_coordinates(db, lat, lon)
                    if maps_links is None:
                        maps_links = generate_google_maps_link(lat, lon)
                finally:
                    db.close()
            except (ValueError, IndexError):
                pass
        
        html_body = f"""
        <html>
        <body>
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #dc2626; color: white; padding: 20px; text-align: center;">
                    <h1>TrustBond System</h1>
                    <h2>Auto-Generated Case Alert</h2>
                </div>
                
                <div style="padding: 20px; background-color: #f8f9fa;">
                    <p>Dear Team,</p>
                    
                    <p>A new case has been automatically generated from verified reports:</p>
                    
                    <div style="background-color: white; padding: 15px; border-left: 4px solid #dc2626; margin: 15px 0;">
                        <h3>{case_number}</h3>
                        <p><strong>Title:</strong> {case_title}</p>
                        <p><strong>Incident Type:</strong> {incident_type}</p>
                        <p><strong>Location:</strong> {location_display}</p>
                        <p><strong>Reports:</strong> {report_count}</p>
                        <p><strong>Status:</strong> Auto-generated from AI-verified reports</p>
                    </div>
                    
                    <p>This case was automatically created when multiple verified reports were clustered together.</p>
                    
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{case_url}" style="background-color: #dc2626; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            Review Case Details
                        </a>
                        {f'<a href="{maps_links["navigation"]}" style="background-color: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">🚗 Navigate to Case Area</a>' if maps_links else ''}
                    </div>
                    
                    {f'<div style="background-color: #fef2f2; padding: 10px; border-radius: 4px; margin: 15px 0;"><p style="margin: 0; font-size: 14px;"><strong>📍 Quick Navigation:</strong> <a href="{maps_links["view"]}" style="color: #dc2626; text-decoration: none;">View on Map</a> | <a href="{maps_links["navigation"]}" style="color: #dc2626; text-decoration: none;">Get Directions</a></p></div>' if maps_links else ''}
                    
                    <p style="font-size: 12px; color: #666; margin-top: 20px;">
                        This is an automated notification from the TrustBond system. 
                        The case was created using AI-powered verification and clustering.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        Auto-Generated Case Alert: {case_number}
        
        Title: {case_title}
        Incident Type: {incident_type}
        Location: {location_display}
        Reports: {report_count}
        Status: Auto-generated from AI-verified reports
        
        This case was automatically created when multiple verified reports were clustered together.
        
        Review the case details at: {case_url}
        {f'Navigate to case area: {maps_links["navigation"]}' if maps_links else ''}
        
        This is an automated notification from the TrustBond system.
        """
        
        # Send to all users with email
        emails = [user.email for user in users_with_email]
        if self.send_email(emails, subject, html_body, text_body):
            successful_sends = len(emails)
        
        return successful_sends
    
    def send_report_verification_notification(
        self,
        police_users: List[PoliceUser],
        report_id: str,
        incident_type: str,
        location: str,
        verification_status: str,
        flag_reason: str = None
    ) -> int:
        """
        Send email notification when a report is verified, flagged, or rejected (for supervisors/admins).
        
        Args:
            police_users: List of police users to notify
            report_id: Report ID
            incident_type: Type of incident
            location: Report location
            verification_status: Verification status
            flag_reason: Reason for flagging (if applicable)
            
        Returns:
            Number of successful email sends
        """
        successful_sends = 0
        
        # Filter users with email addresses
        users_with_email = [user for user in police_users if user.email]
        
        if not users_with_email:
            return 0
        
        # Determine color and title based on status
        if verification_status == "verified":
            status_color = "#10b981"
            status_text = "VERIFIED"
            title = "Report Verified"
        elif verification_status == "under_review" or verification_status == "flagged":
            status_color = "#f59e0b"
            status_text = "FLAGGED FOR REVIEW"
            title = "Report Flagged for Review"
        else:  # rejected
            status_color = "#ef4444"
            status_text = "REJECTED"
            title = "Report Rejected"
        
        subject = f"{title}: {report_id[:8]}..."
        
        report_url = f"{self.frontend_url}/reports/{report_id}"
        
        # Convert coordinates to location hierarchy and generate Google Maps links
        location_display = location
        maps_links = generate_google_maps_link(0, 0)  # Default location
        
        if ',' in location and location.replace(',', '').replace('.', '').replace(' ', '').replace('-', '').isdigit():
            # This looks like coordinates, convert to location hierarchy
            try:
                lat, lon = float(location.split(',')[0]), float(location.split(',')[1])
                db = SessionLocal()
                try:
                    location_display = get_location_hierarchy_from_coordinates(db, lat, lon)
                    maps_links = generate_google_maps_link(lat, lon)
                finally:
                    db.close()
            except (ValueError, IndexError):
                pass
        
        html_body = f"""
        <html>
        <body>
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: {status_color}; color: white; padding: 20px; text-align: center;">
                    <h1>TrustBond System</h1>
                    <h2>{title}</h2>
                </div>
                
                <div style="padding: 20px; background-color: #f8f9fa;">
                    <p>Dear Team,</p>
                    
                    <p>A report has been {status_text.lower()}:</p>
                    
                    <div style="background-color: white; padding: 15px; border-left: 4px solid {status_color}; margin: 15px 0;">
                        <p><strong>Report ID:</strong> {report_id}</p>
                        <p><strong>Incident Type:</strong> {incident_type}</p>
                        <p><strong>Location:</strong> {location_display}</p>
                        <p><strong>Status:</strong> {status_text}</p>
                        {f'<p><strong>Reason:</strong> {flag_reason}</p>' if flag_reason else ''}
                    </div>
                    
                    {'<p><strong>Action Required:</strong> Please review this report and take appropriate action.</p>' if verification_status in ['under_review', 'flagged'] else ''}
                    
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{report_url}" style="background-color: {status_color}; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            View Report Details
                        </a>
                        <a href="{maps_links['navigation']}" style="background-color: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            🚗 Navigate to Location
                        </a>
                    </div>
                    
                    <div style="background-color: #f0f9ff; padding: 10px; border-radius: 4px; margin: 15px 0;">
                        <p style="margin: 0; font-size: 14px;">
                            <strong>📍 Quick Navigation:</strong> 
                            <a href="{maps_links['view']}" style="color: {status_color}; text-decoration: none;">View on Map</a> | 
                            <a href="{maps_links['navigation']}" style="color: {status_color}; text-decoration: none;">Get Directions</a>
                        </p>
                    </div>
                    
                    <p style="font-size: 12px; color: #666; margin-top: 20px;">
                        This is an automated notification from the TrustBond system.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        {title}: {report_id}
        
        Incident Type: {incident_type}
        Location: {location_display}
        Status: {status_text}
        {f'Reason: {flag_reason}' if flag_reason else ''}
        
        {'Action Required: Please review this report and take appropriate action.' if verification_status in ['under_review', 'flagged'] else ''}
        
        View the report details at: {report_url}
        
        This is an automated notification from the TrustBond system.
        """
        
        # Send to all users with email
        emails = [user.email for user in users_with_email]
        if self.send_email(emails, subject, html_body, text_body):
            successful_sends = len(emails)
        
        return successful_sends
    
    def send_report_assignment_notification(
        self,
        police_user: PoliceUser,
        report_id: str,
        incident_type: str,
        location: str,
        flag_reason: str,
        assignment_type: str = "flagged"
    ) -> bool:
        """
        Send email notification when a report is assigned to an officer.
        
        Args:
            police_user: The police user assigned to the report
            report_id: Report ID
            incident_type: Type of incident
            location: Report location
            flag_reason: Reason for flagging/assignment
            assignment_type: Type of assignment (flagged, boundary, etc.)
            
        Returns:
            True if email sent successfully, False otherwise
        """
        if not police_user.email:
            logger.warning(f"Police user {police_user.police_user_id} has no email address")
            return False
        
        subject = f"Report Assigned for Review: {report_id[:8]}..."
        
        report_url = f"{self.frontend_url}/reports/{report_id}"
        
        # Convert coordinates to location hierarchy if needed
        db = SessionLocal()
        try:
            if ',' in location and location.replace(',', '').replace('.', '').replace(' ', '').replace('-', '').isdigit():
                # This looks like coordinates, convert to location hierarchy
                try:
                    lat, lon = float(location.split(',')[0]), float(location.split(',')[1])
                    location_display = get_location_hierarchy_from_coordinates(db, lat, lon)
                    maps_links = generate_google_maps_link(lat, lon)
                except (ValueError, IndexError):
                    location_display = location
                    maps_links = generate_google_maps_link(0, 0)
            else:
                # This is already a location description
                location_display = location
                maps_links = generate_google_maps_link(0, 0)
        finally:
            db.close()
        
        # Customize title and color based on assignment type
        if assignment_type == "boundary":
            title = "Boundary Report Assigned"
            color = "#ef4444"  # Red
            description = "Out-of-boundary report"
            bg_color = "#fef2f2"
            link_color = "#ef4444"
        else:
            title = "Flagged Report Assigned"
            color = "#f59e0b"  # Orange
            description = "Flagged report"
            bg_color = "#fffbeb"
            link_color = "#f59e0b"
        
        html_body = f"""
        <html>
        <body>
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: {color}; color: white; padding: 20px; text-align: center;">
                    <h1>TrustBond System</h1>
                    <h2>{title}</h2>
                </div>
                
                <div style="padding: 20px; background-color: #f8f9fa;">
                    <p>Dear {f"{police_user.first_name} {police_user.last_name}".strip() or police_user.email},</p>
                    
                    <p>A {description} has been assigned to you for review:</p>
                    
                    <div style="background-color: white; padding: 15px; border-left: 4px solid {color}; margin: 15px 0;">
                        <h3>{report_id[:8]}...</h3>
                        <p><strong>Incident Type:</strong> {incident_type}</p>
                        <p><strong>Location:</strong> {location_display}</p>
                        <p><strong>Reason:</strong> {flag_reason}</p>
                    </div>
                    
                    <p><strong>Action Required:</strong> Please review this report and take appropriate action.</p>
                    
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{report_url}" style="background-color: {color}; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            Review Report
                        </a>
                        <a href="{maps_links['navigation']}" style="background-color: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            🚗 Navigate to Location
                        </a>
                    </div>
                    
                    <div style="background-color: {bg_color}; padding: 10px; border-radius: 4px; margin: 15px 0;">
                        <p style="margin: 0; font-size: 14px;">
                            <strong>📍 Quick Navigation:</strong> 
                            <a href="{maps_links['view']}" style="color: {link_color}; text-decoration: none;">View on Map</a> | 
                            <a href="{maps_links['navigation']}" style="color: {link_color}; text-decoration: none;">Get Directions</a>
                        </p>
                    </div>
                    
                    <p style="font-size: 12px; color: #666; margin-top: 20px;">
                        This is an automated notification from the TrustBond system. 
                        If you have questions, please contact your supervisor.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        {title}: {report_id[:8]}...
        
        Incident Type: {incident_type}
        Location: {location}
        Reason: {flag_reason}
        
        Action Required: Please review this report and take appropriate action.
        
        Review the report at: {report_url}
        
        This is an automated notification from the TrustBond system.
        """
        
        return self.send_email([police_user.email], subject, html_body, text_body)
    
    def send_hotspot_notification(
        self,
        police_users: List[PoliceUser],
        hotspot_count: int,
        hotspot_location: str = None,
        hotspot_coordinates: str = None
    ) -> int:
        """
        Send email notification when new hotspots are detected (for supervisors/admins).
        
        Args:
            police_users: List of police users to notify
            hotspot_count: Number of new hotspots detected
            hotspot_location: Location description of primary hotspot
            hotspot_coordinates: Coordinates of primary hotspot
            
        Returns:
            Number of successful email sends
        """
        successful_sends = 0
        
        # Filter users with email addresses
        users_with_email = [user for user in police_users if user.email]
        
        if not users_with_email:
            return 0
        
        subject = f"New Hotspots Detected: {hotspot_count} Safety Hotspots"
        
        # Convert coordinates to location hierarchy and generate Google Maps links
        location_display = hotspot_location
        maps_links = None
        
        if hotspot_coordinates:
            try:
                lat, lon = hotspot_coordinates.split(',')
                lat_float, lon_float = float(lat), float(lon)
                maps_links = generate_google_maps_link(lat_float, lon_float)
                
                # Convert coordinates to location hierarchy
                db = SessionLocal()
                try:
                    location_hierarchy = get_location_hierarchy_from_coordinates(db, lat_float, lon_float)
                    if location_hierarchy and location_hierarchy != f"{lat_float:.4f}, {lon_float:.4f}":
                        # Use location hierarchy if found, otherwise keep original location description
                        location_display = location_hierarchy
                finally:
                    db.close()
            except:
                pass
        
        html_body = f"""
        <html>
        <body>
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #dc2626; color: white; padding: 20px; text-align: center;">
                    <h1>TrustBond System</h1>
                    <h2>🔥 New Safety Hotspots Detected</h2>
                </div>
                
                <div style="padding: 20px; background-color: #f8f9fa;">
                    <p>Dear Team,</p>
                    
                    <p><strong>{hotspot_count}</strong> new safety hotspots have been automatically detected based on recent report clusters.</p>
                    
                    <div style="background-color: white; padding: 15px; border-left: 4px solid #dc2626; margin: 15px 0;">
                        <h3>📍 Hotspot Analysis</h3>
                        <p><strong>Hotspots Detected:</strong> {hotspot_count}</p>
                        <p><strong>Analysis:</strong> AI-powered clustering of verified reports</p>
                        <p><strong>Priority:</strong> Requires immediate attention</p>
                        {f'<p><strong>Primary Location:</strong> {location_display}</p>' if location_display else ''}
                        {f'<p><strong>Coordinates:</strong> {hotspot_coordinates}</p>' if hotspot_coordinates else ''}
                    </div>
                    
                    <p><strong>Action Required:</strong> Please review the Safety Map to assess these hotspots and deploy appropriate resources.</p>
                    
                    <div style="text-align: center; margin: 20px 0;">
                        <a href="{self.frontend_url}/hotspots" style="background-color: #dc2626; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">
                            🔥 View Safety Map
                        </a>
                        {f'<a href="{maps_links["navigation"]}" style="background-color: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 5px;">🚗 Navigate to Hotspot</a>' if maps_links else ''}
                    </div>
                    
                    {f'<div style="background-color: #fef2f2; padding: 10px; border-radius: 4px; margin: 15px 0;"><p style="margin: 0; font-size: 14px;"><strong>📍 Quick Navigation:</strong> <a href="{maps_links["view"]}" style="color: #dc2626; text-decoration: none;">View on Map</a> | <a href="{maps_links["navigation"]}" style="color: #dc2626; text-decoration: none;">Get Directions</a></p></div>' if maps_links else ''}
                    
                    <p style="font-size: 12px; color: #666; margin-top: 20px;">
                        This is an automated notification from the TrustBond system. 
                        Hotspots are generated using AI-powered analysis of report patterns.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        New Safety Hotspots Detected: {hotspot_count} Hotspots
        
        {hotspot_count} new safety hotspots have been automatically detected.
        
        Analysis: AI-powered clustering of verified reports
        Priority: Requires immediate attention
        {f'Primary Location: {location_display}' if location_display else ''}
        {f'Coordinates: {hotspot_coordinates}' if hotspot_coordinates else ''}
        
        Action Required: Please review the Safety Map to assess these hotspots.
        
        View the Safety Map at: {self.frontend_url}/hotspots
        {f'Navigate to hotspot: {maps_links["navigation"]}' if maps_links else ''}
        
        This is an automated notification from the TrustBond system.
        Hotspots are generated using AI-powered analysis of report patterns.
        """
        
        return successful_sends


# Global email service instance
email_service = EmailNotificationService()
