"""
Unit tests for database module (database.py)
"""

import csv
import pytest
from database import init_db, get_session, save_dentist, export_to_crm_csv, get_stats


def test_init_db(tmp_path):
    """Test initializing SQLite database schema."""
    db_file = str(tmp_path / "test_init.db")
    init_db(db_file)
    session = get_session(db_file)
    session.close()


def test_save_and_deduplicate_dentist(tmp_path):
    """Test inserting entries and enforcing deduplication rules."""
    db_file = str(tmp_path / "test_dedup.db")
    init_db(db_file)
    session = get_session(db_file)

    # Insert 1st entry
    d1, created1 = save_dentist(
        session=session,
        practice_name="Lone Star Dentistry",
        state="TX",
        owner_or_management="Dr. Alice Vance, DDS",
        address="123 Main St, Austin, TX",
        phone="(512) 555-0199",
        website="https://lonestardental.com",
    )
    assert created1 is True
    assert d1.id is not None

    # Attempt inserting duplicate by same phone number
    d2, created2 = save_dentist(
        session=session,
        practice_name="Lone Star Dental Care",
        state="TX",
        owner_or_management="Dr. Alice Vance",
        address="123 Main St, Unit B, Austin, TX",
        phone="512-555-0199",  # Same phone digits
        website="https://lonestardental.com",
    )
    assert created2 is False
    assert d2.id == d1.id

    # Attempt inserting duplicate by practice_name + address
    d3, created3 = save_dentist(
        session=session,
        practice_name="lone star dentistry",  # lower case check
        state="TX",
        address="123 Main St, Austin, TX",
        phone="(512) 999-8888",
    )
    assert created3 is False
    assert d3.id == d1.id

    # Insert a distinct practice
    d4, created4 = save_dentist(
        session=session,
        practice_name="Austin Smile Center",
        state="TX",
        owner_or_management="Dr. Bob Marley, DMD",
        address="456 Congress Ave, Austin, TX",
        phone="(512) 555-0200",
    )
    assert created4 is True
    assert d4.id != d1.id

    session.close()


def test_export_to_crm_csv(tmp_path):
    """Test exporting database contents to CRM CSV file."""
    db_file = str(tmp_path / "test_export.db")
    init_db(db_file)
    session = get_session(db_file)

    save_dentist(
        session=session,
        practice_name="Austin Family Dental",
        state="TX",
        owner_or_management="Dr. Clara Oswald",
        address="100 Oak St, Austin, TX",
        phone="(512) 111-2222",
        website="https://austinfamily.com",
    )
    save_dentist(
        session=session,
        practice_name="Miami Sunshine Dental",
        state="FL",
        owner_or_management="Dr. David Miller, DDS",
        address="200 Ocean Dr, Miami, FL",
        phone="(305) 333-4444",
        website="https://miamisunshine.com",
    )
    session.close()

    csv_file = str(tmp_path / "test_crm_export.csv")
    
    # Export state TX only
    exported_count = export_to_crm_csv(state="TX", output_path=csv_file, db_path=db_file)
    assert exported_count == 1

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 2  # Header + 1 record
        assert reader[0][1] == "Company / Practice Name"
        assert reader[1][1] == "Austin Family Dental"
        assert reader[1][6] == "TX"

    # Export all states
    exported_all = export_to_crm_csv(state=None, output_path=csv_file, db_path=db_file)
    assert exported_all == 2


def test_get_stats(tmp_path):
    """Test statistics retrieval from database."""
    db_file = str(tmp_path / "test_stats.db")
    init_db(db_file)
    session = get_session(db_file)

    save_dentist(
        session=session,
        practice_name="Practice A",
        state="TX",
        owner_or_management="Dr. Owner A, DDS",
    )
    save_dentist(
        session=session,
        practice_name="Practice B",
        state="TX",
        owner_or_management="Independent / Unknown",
    )
    save_dentist(
        session=session,
        practice_name="Practice C",
        state="FL",
        owner_or_management="Dr. Owner C, DMD",
    )
    session.close()

    stats = get_stats(db_file)
    assert stats["total_dentists"] == 3
    assert stats["with_owner_extracted"] == 2
    assert stats["state_breakdown"]["TX"] == 2
    assert stats["state_breakdown"]["FL"] == 1
