"""
Database Module (database.py)
Handles SQLite storage, SQLAlchemy ORM modeling, deduplication, and CRM CSV export.
"""

import sqlite3
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DB_PATH = "dentists.db"
engine = create_engine("sqlite:///dentists.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass


class Dentist(Base):
    """
    SQLAlchemy model for dental practice entries.
    """

    __tablename__ = "dentists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    practice_name = Column(String(255), nullable=False)
    owner_or_management = Column(String(255), nullable=True)
    address = Column(String(500), nullable=True)
    phone = Column(String(100), nullable=True)
    website = Column(String(500), nullable=True)
    state = Column(String(10), nullable=False, index=True)
    source = Column(String(255), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("practice_name", "address", name="uix_practice_address"),
    )

    def __repr__(self) -> str:
        return (
            f"<Dentist(id={self.id}, name='{self.practice_name}', "
            f"owner='{self.owner_or_management}', state='{self.state}')>"
        )


def get_engine(db_path: str = DEFAULT_DB_PATH):
    """Create and return SQLAlchemy engine for SQLite."""
    connection_str = f"sqlite:///{db_path}"
    return create_engine(connection_str, echo=False)


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize database and create tables if they do not exist."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)


def get_session(db_path: str = DEFAULT_DB_PATH) -> Session:
    """Create and return a new database session."""
    engine = get_engine(db_path)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def clean_phone(phone: Optional[str]) -> Optional[str]:
    """Normalize phone number string for clean matching."""
    if not phone:
        return None
    # Strip non-digit characters except leading +
    digits = "".join([c for c in phone if c.isdigit()])
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return phone.strip()


def save_dentist(
    session: Session,
    practice_name: str,
    state: str,
    owner_or_management: Optional[str] = None,
    address: Optional[str] = None,
    phone: Optional[str] = None,
    website: Optional[str] = None,
    source: Optional[str] = "Web Scraper",
) -> Tuple[Dentist, bool]:
    """
    Save or update dentist entry enforcing unique constraints across runs.
    Deduplication rules:
      1. Check existing record by normalized phone number (if phone present).
      2. Check existing record by practice_name + address (case-insensitive).
    Returns (Dentist instance, created_boolean).
    """
    practice_name = practice_name.strip()
    state = state.strip().upper()
    phone = clean_phone(phone)
    address = address.strip() if address else None
    website = website.strip() if website else None
    owner_or_management = owner_or_management.strip() if owner_or_management else None

    # Check 1: Deduplication by phone number
    existing: Optional[Dentist] = None
    if phone:
        stmt = select(Dentist).where(Dentist.phone == phone)
        existing = session.scalars(stmt).first()

    # Check 2: Deduplication by practice name + address or practice name + state
    if not existing and address:
        stmt = select(Dentist).where(
            func.lower(Dentist.practice_name) == practice_name.lower(),
            func.lower(Dentist.address) == address.lower(),
        )
        existing = session.scalars(stmt).first()

    if not existing:
        stmt = select(Dentist).where(
            func.lower(Dentist.practice_name) == practice_name.lower(),
            Dentist.state == state,
        )
        existing = session.scalars(stmt).first()

    if existing:
        # Update fields if new information is richer
        updated = False
        if owner_or_management and not existing.owner_or_management:
            existing.owner_or_management = owner_or_management
            updated = True
        elif owner_or_management and existing.owner_or_management == "Independent / Unknown":
            existing.owner_or_management = owner_or_management
            updated = True
        if website and not existing.website:
            existing.website = website
            updated = True
        if phone and not existing.phone:
            existing.phone = phone
            updated = True
        if address and not existing.address:
            existing.address = address
            updated = True
        session.commit()
        return existing, False

    # Insert new record
    new_dentist = Dentist(
        practice_name=practice_name,
        owner_or_management=owner_or_management or "Independent / Unknown",
        address=address,
        phone=phone,
        website=website,
        state=state,
        source=source,
    )
    try:
        session.add(new_dentist)
        session.commit()
        return new_dentist, True
    except IntegrityError:
        session.rollback()
        # Fallback fetch if unique constraint hit
        stmt = select(Dentist).where(
            func.lower(Dentist.practice_name) == practice_name.lower(),
            Dentist.state == state,
        )
        existing = session.scalars(stmt).first()
        return existing or new_dentist, False


def export_to_crm_csv(
    state: Optional[str] = None,
    output_path: str = "crm_export.csv",
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """
    Export dentists from the database to a CRM-formatted CSV file.
    Filters by state if state argument is provided.
    Returns the number of exported rows.
    """
    init_db(db_path)
    session = get_session(db_path)

    query = select(Dentist)
    if state:
        state = state.strip().upper()
        query = query.where(Dentist.state == state)

    query = query.order_by(Dentist.state, Dentist.practice_name)
    results = session.scalars(query).all()

    # Define CRM standard header layout
    fieldnames = [
        "ID",
        "Company / Practice Name",
        "Owner / Doctor Name",
        "Address",
        "Phone",
        "Website",
        "State",
        "Lead Source",
        "Created At",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(fieldnames)
        for d in results:
            writer.writerow(
                [
                    d.id,
                    d.practice_name,
                    d.owner_or_management or "",
                    d.address or "",
                    d.phone or "",
                    d.website or "",
                    d.state,
                    d.source or "Web Scraper",
                    d.created_at.strftime("%Y-%m-%d %H:%M:%S") if d.created_at else "",
                ]
            )

    session.close()
    return len(results)


def get_stats(db_path: str = DEFAULT_DB_PATH) -> Dict:
    """
    Retrieve database statistics.
    Returns dict containing total counts, state breakdown, and owner extraction rate.
    """
    init_db(db_path)
    session = get_session(db_path)

    total_records = session.scalar(select(func.count(Dentist.id))) or 0
    with_owner_count = (
        session.scalar(
            select(func.count(Dentist.id)).where(
                Dentist.owner_or_management.isnot(None),
                Dentist.owner_or_management != "Independent / Unknown",
            )
        )
        or 0
    )

    # Breakdown by state
    state_stmt = (
        select(Dentist.state, func.count(Dentist.id))
        .group_by(Dentist.state)
        .order_by(func.count(Dentist.id).desc())
    )
    state_breakdown = {state: count for state, count in session.execute(state_stmt)}

    session.close()

    return {
        "total_dentists": total_records,
        "with_owner_extracted": with_owner_count,
        "owner_extraction_percentage": (
            round((with_owner_count / total_records) * 100, 2)
            if total_records > 0
            else 0.0
        ),
        "state_breakdown": state_breakdown,
    }

	
import pandas as pd

DB_PATH = "dentists.db"

def init_db(db_path: str = "dentists.db"):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dentists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                practice_name TEXT,
                owner_or_management TEXT,
                address TEXT,
                phone TEXT UNIQUE,
                website TEXT,
                owner_email TEXT,
                owner_linkedin_url TEXT,
                state TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def save_dentist_record(data: dict) -> bool:
    """Saves a single record immediately to disk and skips duplicates."""
    query = """
    INSERT OR IGNORE INTO dentists (
        practice_name, owner_or_management, address, 
        phone, website, state
    ) VALUES (?, ?, ?, ?, ?, ?)
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (
                data.get("practice_name"),
                data.get("owner_or_management"),
                data.get("address"),
                data.get("phone"),
                data.get("website"),
                data.get("state")
            ))
            return cursor.rowcount > 0
    except Exception as e:
        print(f"⚠️ Database error: {e}")
        return False

def export_to_crm_csv(state=None, output_path="crm_export.csv"):
    """Exports database rows to a CSV file."""
    with sqlite3.connect(DB_PATH) as conn:
        query = "SELECT * FROM dentists" if not state or state == "ALL" else f"SELECT * FROM dentists WHERE state = '{state}'"
        df = pd.read_sql_query(query, conn)
        df.to_csv(output_path, index=False)
        print(f"📁 Exported {len(df)} rows to {output_path}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def save_dentist_record(data: dict) -> bool:
    session = SessionLocal()
    try:
        existing = session.query(Dentist).filter(
            Dentist.practice_name == data.get("practice_name"),
            Dentist.state == data.get("state")
        ).first()
        
        if existing:
            return False  # Skip duplicate

        dentist = Dentist(
            practice_name=data.get("practice_name"),
            owner_or_management=data.get("owner_or_management"),
            address=data.get("address"),
            phone=data.get("phone"),
            website=data.get("website"),
            state=data.get("state"),
            source=data.get("source", "crawler")
        )
        session.add(dentist)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"⚠️ Database insert error: {e}")
        return False
    finally:
        session.close()
        
        
Base.metadata.create_all(bind=engine)

# Initialize table on first load
init_db()
