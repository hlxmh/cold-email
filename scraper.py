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


def _decode_cloudflare_email(hex_string: str) -> str | None:
    """Decode Cloudflare email protection (hex-encoded XOR cipher)."""
    try:
        # Extract the email key (first 2 characters become the XOR key)
        key = int(hex_string[0:2], 16)
        # Decode the rest
        email = ""
        for i in range(2, len(hex_string), 2):
            email += chr(int(hex_string[i:i+2], 16) ^ key)
        return email if "@" in email else None
    except (ValueError, IndexError):
        return None


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

    # 3. Cloudflare email protection (encoded in /cdn-cgi/l/email-protection# links)
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if "/cdn-cgi/l/email-protection#" in href:
            hex_part = href.split("/cdn-cgi/l/email-protection#")[-1]
            decoded = _decode_cloudflare_email(hex_part)
            if decoded and _is_valid_email(decoded):
                emails.add(decoded.lower())

    return emails


def _is_company_website_url(url: str) -> bool:
    """Return True if the URL looks like a company's main website."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        # Exclude obvious non-company domains
        non_company = {
            "facebook.com", "twitter.com", "linkedin.com", "instagram.com",
            "youtube.com", "github.com", "gitlab.com", "reddit.com",
            "google.com", "amazon.com", "wikipedia.org",
            "forofficeuseonly.com", "example.com", "test.com",
            "microsoft.com", "windows.com", "apple.com", "mozilla.com",
        }
        
        for excluded in non_company:
            if excluded in domain:
                return False
        
        # Must be a proper domain with at least one dot
        if "." not in domain or len(domain) < 5:
            return False
        
        # Reject domains that sound like placeholders, downloads, or utility sites
        reject_patterns = {
            "cdn-cgi", "login", "oauth", "redirect", "download", "download-",
            "placeholder", "test", "dummy", "sample", "temp", "staging", 
            "dev", "mock", "login", "subscribe", "pdf", "cdn",
        }
        if any(pattern in domain or pattern in path for pattern in reject_patterns):
            return False
        
        return True
    except Exception:
        return False


def _contact_links(html: str, base_url: str) -> list[str]:
    """Return internal links + external company website links that likely lead to contact info."""
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()
        text: str = tag.get_text(" ", strip=True).lower()
        href_lower = href.lower()

        full_url = urljoin(base_url, href)
        
        # Check for contact-related keywords (for internal links)
        is_contact = any(
            kw in href_lower or kw in text for kw in _CONTACT_KEYWORDS
        )
        
        # Check if link text looks like a URL/website (e.g., "http://www.example.com")
        is_url_like = href_lower.startswith(("http://", "https://")) and ("www." in href_lower or ".com" in href_lower or ".net" in href_lower)
        
        # Check if it's an internal link on the same domain with contact keywords
        is_internal_contact = (
            is_contact and 
            urlparse(full_url).netloc == base_domain
        )
        
        # Check if it's an external company website link
        is_external_company = (
            urlparse(full_url).netloc != base_domain and
            _is_company_website_url(full_url) and
            (is_contact or 
             is_url_like or
             any(kw in text for kw in {"website", "visit", "view", "home", "http"}))
        )
        
        if not (is_internal_contact or is_external_company):
            continue

        if full_url not in seen:
            seen.add(full_url)
            links.append(full_url)

    # Prioritize links with "contact" in the URL to visit them first
    contact_first = sorted(links, key=lambda url: ("contact" not in url.lower(), url))
    return contact_first


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
    
    Strategy:
    1. Scrape the root page for emails.
    2. If no emails found, follow internal contact links.
    3. Always try external company website links (they may have company-specific contact info).
    4. For external company websites, also follow their internal contact links if needed.
    """
    # Normalise — add https:// if the caller omitted a scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    visited: set[str] = set()
    all_emails: set[str] = set()
    pages_visited = [0]  # Track pages visited with list to allow modification in nested function

    def visit(page_url: str) -> str | None:
        pages_visited[0] += 1
        if page_url in visited or pages_visited[0] > max_pages:
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

    # If no emails yet, crawl probable internal contact pages
    if not all_emails and root_html:
        for link in _contact_links(root_html, url):
            # Separate external company links from internal links
            external_domain = urlparse(link).netloc != urlparse(url).netloc
            if not external_domain:
                # Internal link: follow it if we haven't found emails yet
                visit(link)
                if all_emails:
                    break

    # Always try external company website links (they may have company-specific contact info)
    if root_html:
        base_domain = urlparse(url).netloc
        external_links = [
            link for link in _contact_links(root_html, url)
            if urlparse(link).netloc != base_domain
        ]
        for external_link in external_links:
            if pages_visited[0] >= max_pages:
                break
            emails_before = len(all_emails)
            external_root_html = visit(external_link)
            
            # If no emails found on external company's main page,
            # also follow their internal contact links
            if pages_visited[0] < max_pages and not all_emails or (len(all_emails) == emails_before and external_root_html):
                for external_contact_link in _contact_links(external_root_html, external_link):
                    # Check if this is an internal link on the external company's domain
                    external_company_domain = urlparse(external_link).netloc
                    if urlparse(external_contact_link).netloc == external_company_domain:
                        if pages_visited[0] >= max_pages:
                            break
                        visit(external_contact_link)
                        if all_emails:
                            # Found emails, exit all loops
                            return sorted(all_emails)
            
            if len(all_emails) > emails_before:
                # Found new emails from this external link
                break

    return sorted(all_emails)
