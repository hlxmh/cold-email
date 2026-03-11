"""
scraper.py — Scrapes a website to discover email addresses.

Strategy:
1. Fetch the given URL and extract emails from the raw HTML.
2. Also parse mailto: href links (reliable contact addresses).
3. If no emails are found, follow internal links whose text/href
   suggests a contact page and repeat the search.
"""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote

# Matches standard email addresses; avoids matching image/font filenames.
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Suffixes that commonly appear in CSS/JS asset paths, not real addresses.
_ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

# Keywords that suggest a page contains contact info.
_CONTACT_KEYWORDS = {
    "contact", "contacts", "reach", "connect",
    "about", "team", "people", "support", "help", "imprint",
}

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _is_valid_email(address: str) -> bool:
    """Return True if the address looks like a real email, not an asset path."""
    local, _, domain = address.rpartition("@")
    if not local or not domain:
        return False
    # Reject anything where the local-part ends with a known asset suffix
    lower = address.lower()
    if any(lower.endswith(sfx) for sfx in _ASSET_SUFFIXES):
        return False
    # Must have at least one dot in the domain
    if "." not in domain:
        return False
    return True


def _extract_emails_from_html(html: str) -> set[str]:
    """Pull email addresses from raw HTML text and mailto: href values."""
    emails: set[str] = set()

    # 1. Raw regex over the whole page text
    for match in _EMAIL_RE.finditer(html):
        addr = match.group(0)
        if _is_valid_email(addr):
            emails.add(addr.lower())

    # 2. Explicit mailto: links (highest confidence)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if href.lower().startswith("mailto:"):
            # Strip query string (subject=, body=, etc.)
            raw = unquote(href[7:].split("?")[0]).strip()
            if _EMAIL_RE.match(raw) and _is_valid_email(raw):
                emails.add(raw.lower())

    return emails


def _contact_links(html: str, base_url: str) -> list[str]:
    """Return internal links that are likely to lead to a contact page."""
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()
        text: str = tag.get_text(" ", strip=True).lower()
        href_lower = href.lower()

        is_contact = any(
            kw in href_lower or kw in text for kw in _CONTACT_KEYWORDS
        )
        if not is_contact:
            continue

        full_url = urljoin(base_url, href)
        # Only follow links that stay on the same domain
        if urlparse(full_url).netloc != base_domain:
            continue
        if full_url not in seen:
            seen.add(full_url)
            links.append(full_url)

    return links


def _fetch(url: str, timeout: int = 12) -> str | None:
    """GET a URL and return the response text, or None on failure."""
    try:
        resp = requests.get(url, headers=_DEFAULT_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(f"  [warning] Could not fetch {url}: {exc}")
        return None


def scrape_company_name(url: str) -> str:
    """
    Best-effort extraction of a human-readable company name from *url*.

    Priority order:
      1. <meta property="og:site_name"> / <meta name="application-name">
      2. First segment of the <title> tag (before | - –)
      3. Domain name with TLD stripped, title-cased
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    html = _fetch(url)
    if html:
        soup = BeautifulSoup(html, "lxml")

        # 1. Open Graph site name / application-name
        for attr_key, attr_val in [("property", "og:site_name"), ("name", "application-name")]:
            tag = soup.find("meta", attrs={attr_key: attr_val})
            value = tag.get("content", "").strip() if tag else ""
            # Reject if it looks like a sentence (too long or too many words)
            if value and len(value) <= 60 and value.count(" ") <= 5:
                return value

        # 2. <title> first segment
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            import re as _re
            segment = _re.split(r"[|\-–—]", title_tag.string)[0].strip()
            if segment:
                return segment

    # 3. Fallback: derive from domain
    domain = urlparse(url).netloc.lower().lstrip("www.")
    # Strip TLD(s): everything before the last dot
    name_part = domain.rsplit(".", 1)[0]
    # Replace hyphens/underscores with spaces and title-case
    return name_part.replace("-", " ").replace("_", " ").title()


def scrape_website_for_emails(url: str, max_pages: int = 6) -> list[str]:
    """
    Scrape *url* (and up to *max_pages* internal contact-related pages)
    for email addresses. Returns a de-duplicated list sorted alphabetically.
    """
    # Normalise — add https:// if the caller omitted a scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    visited: set[str] = set()
    all_emails: set[str] = set()

    def visit(page_url: str) -> str | None:
        if page_url in visited or len(visited) >= max_pages:
            return None
        visited.add(page_url)
        print(f"  Fetching: {page_url}")
        html = _fetch(page_url)
        if html:
            found = _extract_emails_from_html(html)
            if found:
                print(f"    Found {len(found)} email(s): {', '.join(sorted(found))}")
            all_emails.update(found)
        return html

    # Always start with the root page
    root_html = visit(url)

    # If no emails yet, crawl probable contact pages
    if not all_emails and root_html:
        for link in _contact_links(root_html, url):
            visit(link)
            if all_emails:
                # One successful contact page is usually enough
                break

    return sorted(all_emails)
