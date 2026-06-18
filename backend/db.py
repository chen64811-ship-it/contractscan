"""
Database connection (SQLAlchemy)
Reads `DATABASE_URL` from environment (e.g. mysql+pymysql://user:pass@db:3306/contractscan)
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
else:
    engine = None
    SessionLocal = None

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session.

    Raises RuntimeError if the database is not configured.
    """
    if SessionLocal is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL in environment.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
