#!/usr/bin/env python3
"""
Script to check reports in the database and potentially add test data
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from app.config import settings
from app.database import Base
from app.models.report import Report
from app.models.device import Device
from app.models.incident_type import IncidentType
from app.models.location import Location
from sqlalchemy.orm import sessionmaker

def check_reports():
    """Check reports in the database"""
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Count total reports
        total_reports = session.query(Report).count()
        print(f"📊 Total reports in database: {total_reports}")
        
        if total_reports > 0:
            # Show status breakdown
            status_counts = session.execute(
                text("SELECT status, COUNT(*) FROM reports GROUP BY status")
            ).fetchall()
            print(f"📈 Status breakdown: {dict(status_counts)}")
            
            # Show verification status breakdown
            verification_counts = session.execute(
                text("SELECT verification_status, COUNT(*) FROM reports GROUP BY verification_status")
            ).fetchall()
            print(f"🔍 Verification breakdown: {dict(verification_counts)}")
            
            # Show recent reports
            recent_reports = session.execute(
                text("SELECT report_id, status, verification_status, reported_at FROM reports ORDER BY reported_at DESC LIMIT 5")
            ).fetchall()
            print(f"📋 Recent reports:")
            for report in recent_reports:
                print(f"  - {report[0]} | {report[1]} | {report[2]} | {report[3]}")
        else:
            print("⚠️  No reports found in database")
            
            # Check if we have devices and incident types for creating test reports
            device_count = session.query(Device).count()
            incident_type_count = session.query(IncidentType).count()
            location_count = session.query(Location).filter(Location.location_type == "sector").count()
            
            print(f"📱 Available devices: {device_count}")
            print(f"🚨 Available incident types: {incident_type_count}")
            print(f"📍 Available sectors: {location_count}")
            
            if device_count > 0 and incident_type_count > 0 and location_count > 0:
                print("\n✅ Database has required data for creating test reports")
                print("💡 You can create test reports using the mobile app or API")
            else:
                print("\n❌ Missing required data for creating reports:")
                if device_count == 0:
                    print("   - No devices found")
                if incident_type_count == 0:
                    print("   - No incident types found")
                if location_count == 0:
                    print("   - No sector locations found")
        
    except Exception as e:
        print(f"❌ Error checking reports: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    print("🔍 Checking reports in database...")
    check_reports()
