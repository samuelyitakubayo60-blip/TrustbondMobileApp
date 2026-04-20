from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,  # Recycle connections every 30 minutes
    pool_timeout=30,
    connect_args={
        "connect_timeout": 60,
        "application_name": "trustbond_backend",
        "options": "-c statement_timeout=30000"  # 30 second query timeout
    },
    echo=False  # Set to True for SQL debugging if needed
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_with_retry(max_retries=3):
    """Get database session with retry logic for connection issues"""
    import time
    from sqlalchemy.exc import OperationalError
    
    for attempt in range(max_retries):
        try:
            db = SessionLocal()
            # Test the connection
            db.execute("SELECT 1")
            return db
        except OperationalError as e:
            if attempt == max_retries - 1:
                raise
            print(f"Database connection attempt {attempt + 1} failed, retrying in 1 second...")
            time.sleep(1)
        except Exception:
            if db:
                db.close()
            raise
