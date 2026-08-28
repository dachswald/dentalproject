"""
Unit tests for crawler module (crawler.py)
"""

import pytest
from crawler import (
    is_dso,
    extract_owner_from_text,
    parse_page_for_owner,
    fetch_fallback_directory_dentists,
)


def test_dso_exclusion():
    """Test filtering corporate DSOs vs independent dental practices."""
    assert is_dso("Aspen Dental of Austin", website="https://aspendental.com") is True
    assert is_dso("Heartland Dental Care", operator="Heartland Dental") is True
    assert is_dso("Pacific Dental Services", website="https://pacificdentalservices.com") is True
    assert is_dso("Western Dental & Orthodontics") is True
    assert is_dso("Smile Brands Inc.") is True

    # Independent practices should pass
    assert is_dso("Austin Family Dental Studio", website="https://austinfamilydental.com") is False
    assert is_dso("Oakwood Pediatric Dentistry", operator="Independent") is False


def test_extract_owner_from_text():
    """Test regex and NLP name extraction heuristics from text snippets."""
    sample1 = "Welcome to our clinic! Our founding dentist is Dr. Sarah Connor, DDS who has 15 years experience."
    assert extract_owner_from_text(sample1) in ["Dr. Sarah Connor, DDS", "Dr. Sarah Connor"]

    sample2 = "Meet Dr. Marcus Brody, DMD - lead practitioner at Indiana Dental."
    assert extract_owner_from_text(sample2) in ["Dr. Marcus Brody, DMD", "Dr. Marcus Brody"]

    sample3 = "Lead Dentist: Dr. Henry Walton"
    assert extract_owner_from_text(sample3) == "Dr. Henry Walton"

    sample4 = "John Smith, DDS has been practicing in Dallas since 2010."
    assert extract_owner_from_text(sample4) in ["John Smith, DDS", "Dr. John Smith, DDS"]


def test_parse_page_for_owner_html():
    """Test HTML parsing for dentist owner extraction."""
    html_doc = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Meet the Doctor - Austin Premier Dentistry</title>
        <meta name="description" content="Dr. Elizabeth Bennet, DDS provides gentle dental care in Austin TX.">
    </head>
    <body>
        <h1>Welcome to Austin Premier Dentistry</h1>
        <div class="team-member">
            <h2>Meet Dr. Elizabeth Bennet, DDS</h2>
            <p>Dr. Bennet graduated from UT San Antonio Dental School.</p>
        </div>
    </body>
    </html>
    """
    extracted = parse_page_for_owner(html_doc)
    assert extracted is not None
    assert "Elizabeth Bennet" in extracted


def test_fetch_fallback_directory_dentists():
    """Test state fallback directory listing generator."""
    practices = fetch_fallback_directory_dentists("TX", limit=5)
    assert len(practices) == 5
    assert practices[0]["state"] if "state" in practices[0] else "TX" in practices[0]["address"]
    assert "Family Dental Care" in practices[0]["practice_name"] or "Smiles" in practices[0]["practice_name"]
