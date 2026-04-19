#!/usr/bin/env python3
"""Script to add missing audit log fields to database"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def add_audit_log_fields():
    """Add missing audit log fields to the database"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment variables")
        return False
    
    try:
        # Create database connection
        engine = create_engine(database_url)
        
        # SQL commands to add missing fields
        sql_commands = [
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_role VARCHAR(50);",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS masked_details JSONB;",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20);",
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_role ON audit_logs(actor_role);",
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_sensitivity_level ON audit_logs(sensitivity_level);"
        ]
        
        with engine.connect() as connection:
            for command in sql_commands:
                print(f"Executing: {command}")
                connection.execute(text(command))
            connection.commit()
            
        print("✅ Successfully added audit log fields to database")
        return True
        
    except Exception as e:
        print(f"❌ Error adding audit log fields: {e}")
        return False

if __name__ == "__main__":
    success = add_audit_log_fields()
    sys.exit(0 if success else 1)
