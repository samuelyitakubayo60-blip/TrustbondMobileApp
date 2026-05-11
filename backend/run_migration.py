#!/usr/bin/env python3
"""
Simple migration runner for deployment decisions and suspect tracking
"""
import os
import sys
from sqlalchemy import create_engine, text
from app.config import settings

def run_migration():
    """Run the deployment decisions and suspect tracking migration"""
    
    # Create database engine
    database_url = settings.database_url
    engine = create_engine(database_url)
    
    print("Running deployment decisions and suspect tracking migration...")
    
    try:
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                # Create deployment_decisions table
                print("Creating deployment_decisions table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS deployment_decisions (
                        decision_id SERIAL PRIMARY KEY,
                        report_id UUID NOT NULL REFERENCES reports(report_id),
                        case_id UUID REFERENCES cases(case_id),
                        decided_by INTEGER NOT NULL REFERENCES police_users(police_user_id),
                        deployment_status VARCHAR(20),
                        assigned_unit VARCHAR(80),
                        deployment_priority VARCHAR(20),
                        decision_note TEXT,
                        leader_confirmation_weight INTEGER,
                        deployed_at TIMESTAMP WITH TIME ZONE,
                        estimated_arrival TIMESTAMP WITH TIME ZONE,
                        actual_arrival TIMESTAMP WITH TIME ZONE,
                        deployment_outcome VARCHAR(50),
                        outcome_note TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """))
                
                # Create suspect_victim_tracking table
                print("Creating suspect_victim_tracking table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS suspect_victim_tracking (
                        tracking_id SERIAL PRIMARY KEY,
                        case_id UUID NOT NULL REFERENCES cases(case_id),
                        person_type VARCHAR(20) NOT NULL,
                        full_name VARCHAR(200) NOT NULL,
                        national_id VARCHAR(30),
                        phone_number VARCHAR(20),
                        age INTEGER,
                        gender VARCHAR(10),
                        status VARCHAR(30),
                        status_note TEXT,
                        rib_case_number VARCHAR(50),
                        rib_handover_date TIMESTAMP WITH TIME ZONE,
                        rib_officer_name VARCHAR(200),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """))
                
                # Create special_assignment_units table
                print("Creating special_assignment_units table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS special_assignment_units (
                        unit_id SERIAL PRIMARY KEY,
                        unit_code VARCHAR(50) NOT NULL UNIQUE,
                        unit_name VARCHAR(100) NOT NULL,
                        description VARCHAR(500),
                        is_active BOOLEAN DEFAULT TRUE,
                        requires_commander_approval BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """))
                
                # Insert standard special assignment units
                print("Inserting standard special assignment units...")
                units = [
                    ('general_patrol', 'General Patrol', 'Regular patrol officers for routine incidents'),
                    ('quick_response', 'Quick Response Team', 'Rapid response team for urgent incidents'),
                    ('counter_terror', 'Counter Terrorism', 'Specialized counter-terrorism unit'),
                    ('fire_rescue', 'Fire & Rescue', 'Fire fighting and rescue operations'),
                    ('rib', 'Rwanda Investigation Bureau', 'National investigation bureau for serious cases')
                ]
                
                for unit_code, unit_name, description in units:
                    conn.execute(text("""
                        INSERT INTO special_assignment_units (unit_code, unit_name, description, requires_commander_approval)
                        VALUES (:unit_code, :unit_name, :description, :requires_approval)
                        ON CONFLICT (unit_code) DO NOTHING
                    """), {
                        'unit_code': unit_code,
                        'unit_name': unit_name,
                        'description': description,
                        'requires_approval': unit_code != 'general_patrol'  # General patrol doesn't require approval
                    })
                
                # Create indexes
                print("Creating indexes...")
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_deployment_decisions_report_id ON deployment_decisions(report_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_deployment_decisions_decided_by ON deployment_decisions(decided_by)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_deployment_decisions_deployment_status ON deployment_decisions(deployment_status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_suspect_victim_tracking_case_id ON suspect_victim_tracking(case_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_suspect_victim_tracking_person_type ON suspect_victim_tracking(person_type)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_suspect_victim_tracking_status ON suspect_victim_tracking(status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_special_assignment_units_unit_code ON special_assignment_units(unit_code)"))
                
                # Commit transaction
                trans.commit()
                print("✅ Migration completed successfully!")
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                print(f"❌ Migration failed: {e}")
                raise
                
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
