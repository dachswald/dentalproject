"""
Scraping & Discovery Module (crawler.py)
Handles ZIP-by-ZIP dental practice discovery via OpenStreetMap Overpass API,
DSO/Corporate exclusion filtering, stealth web scraping with rate limiting & user-agent rotation,
and Dentist/Owner name extraction via regex and NLP heuristics.
"""

import random
import re
import sys
import time
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import httpx
import zipcodes
from bs4 import BeautifulSoup
from database import init_db, save_dentist_record

# Try loading Playwright if available
playwright_available = False
try:
    from playwright.sync_api import sync_playwright
    playwright_available = True
except ImportError:
    playwright_available = False

# Try loading spaCy if installed
nlp_model = None
try:
    import spacy
    try:
        nlp_model = spacy.load("en_core_web_sm")
    except Exception:
        nlp_model = None
except ImportError:
    nlp_model = None

# DSO / Corporate Dental Exclusion List
DSO_EXCLUSION_LIST = [
    "aspen dental", "heartland dental", "pacific dental", "smile brands",
    "western dental", "great expressions", "gentle dental", "affordable dentures",
    "dental care alliance", "coast dental", "monarch dental", "bright now",
    "castle dental", "interdent", "ricoba", "comfort dental", "midwest dental",
    "chicagoland smile", "dental one", "benevis", "kool smiles", "small smiles",
    "ideal dental", "decision one dental", "mb2 dental", "apex dental", "mortenson dental"
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edge/120.0.0.0",
]


def get_random_headers() -> Dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }


def is_dso(practice_name: str, website: str = "", operator: str = "") -> bool:
    combined_text = f"{practice_name} {website} {operator}".lower()
    return any(dso in combined_text for dso in DSO_EXCLUSION_LIST)


DOCTOR_NAME_PATTERNS = [
    re.compile(r"(?:Dr\.|Doctor)\s+([A-Z][a-zA-Z'\-]+\s+(?:[A-Z]\.\s+)?[A-Z][a-zA-Z'\-]+)(?:\s*,?\s*(?:DDS|DMD|D\.D\.S\.|D\.M\.D\.|FAGD|MAGD))?", re.IGNORECASE),
    re.compile(r"\b([A-Z][a-zA-Z'\-]+\s+(?:[A-Z]\.\s+)?[A-Z][a-zA-Z'\-]+)\s*,\s*(?:DDS|DMD|D\.D\.S\.|D\.M\.D\.|FAGD|MAGD)\b", re.IGNORECASE),
    re.compile(r"(?:Owner|Founder|Lead Dentist|Chief Dentist|Managing Dentist|Practitioner|Practice Owner)\s*:\s*(?:Dr\.\s+)?([A-Z][a-zA-Z'\-]+\s+[A-Z][a-zA-Z'\-]+)", re.IGNORECASE),
]


def extract_owner_from_text(text: str) -> Optional[str]:
    if not text:
        return None

    for pattern in DOCTOR_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_name = re.sub(r"\s+", " ", match.group(0).strip())
            if not raw_name.lower().startswith("dr") and not raw_name.lower().startswith("doctor"):
                if "DDS" in raw_name or "DMD" in raw_name:
                    return raw_name
                return f"Dr. {raw_name}"
            return raw_name

    if nlp_model:
        doc = nlp_model(text[:5000])
        for ent in doc.ents:
            if ent.label_ == "PERSON" and len(ent.text.split()) in (2, 3):
                start = max(0, ent.start_char - 30)
                end = min(len(text), ent.end_char + 30)
                context = text[start:end].lower()
                if any(k in context for k in ["dr", "doctor", "dds", "dmd", "dentist", "owner"]):
                    name = ent.text.strip()
                    return f"Dr. {name}" if not name.lower().startswith("dr") else name

    return None


def parse_page_for_owner(html_content: str) -> Optional[str]:
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, "lxml")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        owner = extract_owner_from_text(meta_desc["content"])
        if owner:
            return owner

    title_tag = soup.find("title")
    if title_tag and title_tag.text:
        owner = extract_owner_from_text(title_tag.text)
        if owner:
            return owner

    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "div", "span"]):
        text = tag.get_text(separator=" ", strip=True)
        if any(keyword in text.lower() for keyword in ["meet", "doctor", "dr.", "dds", "dmd", "owner", "dentist"]):
            owner = extract_owner_from_text(text)
            if owner:
                return owner

    return None


def scrape_website_for_owner(website_url: str, client: httpx.Client) -> Optional[str]:
    if not website_url:
        return None

    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    try:
        resp = client.get(website_url, follow_redirects=True, timeout=httpx.Timeout(2.5, connect=1.5))
        if resp.status_code == 200:
            owner = parse_page_for_owner(resp.text)
            if owner:
                return owner

            soup = BeautifulSoup(resp.text, "lxml")
            subpage_urls: Set[str] = set()

            for link in soup.find_all("a", href=True):
                href = link["href"].lower()
                link_text = link.get_text().lower()
                if any(kw in href or kw in link_text for kw in ["about", "doctor", "team", "staff", "meet"]):
                    full_sub_url = urljoin(website_url, link["href"])
                    if urlparse(full_sub_url).netloc == urlparse(website_url).netloc:
                        subpage_urls.add(full_sub_url)
                        if len(subpage_urls) >= 2:
                            break

            for sub_url in subpage_urls:
                time.sleep(random.uniform(0.2, 0.5))
                sub_resp = client.get(sub_url, follow_redirects=True, timeout=httpx.Timeout(2.5, connect=1.5))
                if sub_resp.status_code == 200:
                    sub_owner = parse_page_for_owner(sub_resp.text)
                    if sub_owner:
                        return sub_owner
    except Exception:
        pass

    return None


def get_state_zip_codes(state_abbr: str) -> List[str]:
    """Retrieve all active ZIP codes for a given US state code (e.g. 'TX')."""
    matches = zipcodes.filter_by(state=state_abbr.upper(), active=True)
    return [z['zip_code'] for z in matches]


def fetch_dentists_by_zip(zip_code: str, state: str) -> List[Dict]:
    """Query OpenStreetMap Overpass API specifically for dentists within a postal code."""
    overpass_url = "https://overpass-api.de/api/interpreter"
    
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="dentist"]["addr:postcode"="{zip_code}"];
      node["healthcare"="dentist"]["addr:postcode"="{zip_code}"];
      way["amenity"="dentist"]["addr:postcode"="{zip_code}"];
    );
    out center;
    """

    practices = []
    try:
        with httpx.Client(timeout=20.0, headers=get_random_headers()) as client:
            response = client.post(overpass_url, data={"data": query})
            if response.status_code == 200:
                data = response.json()
                for elem in data.get("elements", []):
                    tags = elem.get("tags", {})
                    name = tags.get("name")
                    if not name:
                        continue

                    street = tags.get("addr:street", "")
                    housenumber = tags.get("addr:housenumber", "")
                    city = tags.get("addr:city", "")
                    postcode = tags.get("addr:postcode", zip_code)

                    addr_parts = [p for p in [f"{housenumber} {street}".strip(), city, f"{state.upper()} {postcode}".strip()] if p]
                    full_address = ", ".join(addr_parts) if addr_parts else None

                    phone = tags.get("phone") or tags.get("contact:phone")
                    website = tags.get("website") or tags.get("contact:website")
                    operator = tags.get("operator", "")

                    practices.append({
                        "practice_name": name,
                        "address": full_address,
                        "phone": phone,
                        "website": website,
                        "operator": operator,
                        "source": f"OSM ZIP {zip_code}",
                    })
    except Exception as e:
        print(f"  [!] Notice querying ZIP {zip_code}: {e}")

    return practices


def crawl_state(
    state: str,
    limit: int = 1000,
    db_path: str = "dentists.db",
    verbose: bool = True,
    delay_range: tuple = (1.0, 2.5),
    on_progress=None
) -> Dict:
    """Iterate through ZIP codes for the state, extracting records into SQLite."""
    state = state.upper()
    init_db(db_path)

    all_zips = get_state_zip_codes(state)
    total_zips = len(all_zips)
    if verbose:
        print(f"[*] Found {total_zips} ZIP codes for {state}. Target limit: {limit} records.")

    saved_count = 0
    dso_excluded_count = 0
    extracted_owner_count = 0
    total_discovered = 0

    with httpx.Client(headers=get_random_headers(), timeout=12.0) as client:
        for idx, zip_code in enumerate(all_zips, start=1):
            if saved_count >= limit:
                if verbose:
                    print(f"[*] Target limit of {limit} records reached.")
                break

            if verbose:
                print(f"[{idx}/{total_zips}] Querying ZIP: {zip_code} (Saved so far: {saved_count})...")

            discovered = fetch_dentists_by_zip(zip_code, state)
            total_discovered += len(discovered)

            for entry in discovered:
                if saved_count >= limit:
                    break

                p_name = entry["practice_name"]
                p_website = entry.get("website") or ""
                p_operator = entry.get("operator") or ""

                if is_dso(p_name, p_website, p_operator):
                    dso_excluded_count += 1
                    continue

                owner_name = None
                if p_website:
                    owner_name = scrape_website_for_owner(p_website, client)
                    time.sleep(random.uniform(*delay_range))

                if owner_name:
                    extracted_owner_count += 1
                else:
                    owner_name = "Independent / Unknown"

                record = {
                    "practice_name": p_name,
                    "owner_or_management": owner_name,
                    "address": entry.get("address"),
                    "phone": entry.get("phone"),
                    "website": p_website,
                    "state": state,
                    "source": entry.get("source", "OSM"),
                }

                if save_dentist_record(record):
                    saved_count += 1
                    if verbose:
                        print(f"  💾 Saved: {record['practice_name']}")
                    if on_progress:
                        on_progress(saved_count, limit, record['practice_name'])
                else:
                    if verbose:
                        print(f"  ⏩ Duplicate skipped: {record['practice_name']}")

            # Pause between ZIP queries
            time.sleep(random.uniform(0.5, 1.2))

    summary = {
        "state": state,
        "total_discovered": total_discovered,
        "dso_excluded": dso_excluded_count,
        "saved_to_db": saved_count,
        "extracted_owners": extracted_owner_count,
    }

    if verbose:
        print("\n[=] Crawl Run Completed:")
        print(f"    - Discovered: {summary['total_discovered']}")
        print(f"    - DSO Excluded: {summary['dso_excluded']}")
        print(f"    - Saved to DB: {summary['saved_to_db']}")
        print(f"    - Owners Found: {summary['extracted_owners']}")

    return summary