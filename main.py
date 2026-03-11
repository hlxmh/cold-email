#!/usr/bin/env python3
"""
main.py — Cold Email CLI

Usage examples
--------------
# Compose email inline and attach files:
python main.py \\
    --from-email you@outlook.com \\
    --website https://example.com \\
    --subject "Hello from me" \\
    --body-file template.html \\
    --attachments brochure.pdf deck.pptx

# Use an existing .eml file as the message template:
python main.py \\
    --from-email you@outlook.com \\
    --website https://example.com \\
    --eml sample.eml

# Preview discovered emails without sending:
python main.py --website https://example.com --dry-run

Credentials can also be set via environment variables or a .env file:
    GMAIL_EMAIL=you@gmail.com
    GMAIL_APP_PASSWORD=your-16-char-app-password
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from mailer import build_message, build_message_from_eml, send_message
from scraper import scrape_website_for_emails


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="cold-email",
        description="Find an email address on a website and send a cold email via Outlook.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Gmail account ────────────────────────────────────────────────────
    account = p.add_argument_group("Gmail account")
    account.add_argument(
        "--from-email", "-f",
        metavar="ADDRESS",
        help="Your Gmail address (env: GMAIL_EMAIL).",
    )
    account.add_argument(
        "--password", "-p",
        metavar="PASSWORD",
        help="Gmail App Password (env: GMAIL_APP_PASSWORD). "
             "Generate one at myaccount.google.com/apppasswords. "
             "If omitted, you will be prompted securely.",
    )

    # ── Target website ───────────────────────────────────────────────────────
    p.add_argument(
        "--website", "-w",
        metavar="URL",
        help="Website to scrape for recipient email addresses.",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=6,
        metavar="N",
        help="Maximum number of pages to crawl (default: 6).",
    )
    p.add_argument(
        "--company-name", "-n",
        metavar="NAME",
        help="Company name to use in the greeting (e.g. 'DXA Studio'). "
             "If omitted, you will be prompted interactively.",
    )

    # ── Message source: .eml file OR inline fields ───────────────────────────
    source = p.add_argument_group(
        "Message source",
        "Provide EITHER --eml-file OR the --subject / --body* / --attachments flags.",
    )
    source.add_argument(
        "--eml-file", "-e",
        metavar="FILE",
        help="Path to a .eml file whose content (subject, body, attachments) "
             "will be re-sent as-is.",
    )
    source.add_argument(
        "--subject", "-s",
        metavar="TEXT",
        help="Email subject line.",
    )
    source.add_argument(
        "--body", "-b",
        metavar="TEXT",
        help="Email body as a plain-text string.",
    )
    source.add_argument(
        "--body-file",
        metavar="FILE",
        help="Path to a .txt or .html file whose contents become the email body. "
             ".html files are sent as HTML automatically.",
    )
    source.add_argument(
        "--attachments", "-a",
        nargs="+",
        metavar="FILE",
        default=[],
        help="One or more file paths to attach to the email.",
    )
    source.add_argument(
        "--html",
        action="store_true",
        help="Treat --body / --body-file as HTML (auto-set for .html files).",
    )

    # ── Behaviour flags ──────────────────────────────────────────────────────
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape the website and show found addresses, but do NOT send anything.",
    )

    return p.parse_args()


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _prompt_multiline(prompt: str) -> str:
    """Read multi-line input; end with a blank line."""
    print(f"{prompt} (press Enter on a blank line to finish):")
    lines: list[str] = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _save_to_dotenv(key: str, value: str, dotenv_path: str = ".env") -> None:
    """Write or update a KEY=value line in the .env file."""
    path = Path(dotenv_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    prefix = f"{key}="
    new_line = f"{key}={value}\n"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            path.write_text("".join(lines), encoding="utf-8")
            return
    # Key not found — append it
    with path.open("a", encoding="utf-8") as fh:
        fh.write(new_line)


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    """Return (from_email, password), prompting for anything still missing."""
    from_email = args.from_email or os.getenv("GMAIL_EMAIL", "").strip()
    password = args.password or os.getenv("GMAIL_APP_PASSWORD", "").strip()

    if not from_email:
        from_email = input("Gmail address: ").strip()
    if not password:
        password = getpass.getpass(f"App password for {from_email}: ")
        _save_to_dotenv("GMAIL_APP_PASSWORD", password)
        print("  App password saved to .env — won't be asked again.")

    if not from_email or not password:
        _die("Gmail credentials are required to send email.")

    return from_email, password


def _resolve_website(args: argparse.Namespace) -> str:
    url = args.website or os.getenv("TARGET_WEBSITE", "").strip()
    if not url:
        url = input("Website URL to scrape: ").strip()
    if not url:
        _die("A website URL is required.")
    return url


def _resolve_message_fields(
    args: argparse.Namespace,
) -> tuple[str, str, bool]:
    """Return (subject, body, is_html), prompting for anything missing."""
    subject = args.subject or os.getenv("EMAIL_SUBJECT", "").strip()
    body = args.body or ""
    html_body = args.html

    # Load body from file if supplied
    if not body and args.body_file:
        body_path = Path(args.body_file)
        if not body_path.is_file():
            _die(f"Body file not found: {args.body_file}")
        body = body_path.read_text(encoding="utf-8")
        if body_path.suffix.lower() == ".html":
            html_body = True

    if not subject:
        subject = input("Email subject: ").strip()
    if not body:
        body = _prompt_multiline("Email body")

    if not subject:
        _die("An email subject is required.")
    if not body:
        _die("An email body is required.")

    return subject, body, html_body


def _die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Recipient selection
# ---------------------------------------------------------------------------

def _choose_recipients(emails: list[str]) -> list[str]:
    """If multiple addresses were found, let the user pick one or all."""
    if len(emails) == 1:
        return emails

    print("\nMultiple addresses found. Select a recipient:")
    print("  0  Send to ALL")
    for i, addr in enumerate(emails, 1):
        print(f"  {i}  {addr}")

    raw = input("Enter number (default 1): ").strip()
    if raw == "" or raw == "1":
        return [emails[0]]
    try:
        choice = int(raw)
    except ValueError:
        _die("Invalid selection.")
        return []  # unreachable; keeps linter happy

    if choice == 0:
        return emails
    if 1 <= choice <= len(emails):
        return [emails[choice - 1]]
    _die(f"Choice must be between 0 and {len(emails)}.")
    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    args = _parse_args()

    # Validate mutually exclusive message sources
    # (--attachments is allowed with --eml-file as extra local attachments)
    using_eml = bool(args.eml_file)
    using_inline = any([args.subject, args.body, args.body_file])
    if using_eml and using_inline:
        _die("Specify EITHER --eml-file OR --subject/--body, not both.")

    # ── 1. Find the recipient ────────────────────────────────────────────────
    website = _resolve_website(args)
    print(f"\nSearching {website} for email addresses …")
    emails = scrape_website_for_emails(website, max_pages=args.max_pages)
    company_name = args.company_name or input("Company name for greeting (e.g. 'DXA Studio'): ").strip()

    if not emails:
        _die("No email addresses found on the website. Try a different URL.")

    print(f"\nFound {len(emails)} address(es):")
    for addr in emails:
        print(f"  • {addr}")

    if args.dry_run:
        print("\nDry run — nothing sent.")
        return

    recipients = _choose_recipients(emails)

    # ── 2. Gather credentials ────────────────────────────────────────────────
    from_email, password = _resolve_credentials(args)

    # ── 3. Build the message ─────────────────────────────────────────────────
    for to_email in recipients:
        print(f"\nPreparing email to {to_email} …")

        if using_eml:
            eml_path = args.eml_file
            if not Path(eml_path).is_file():
                _die(f".eml file not found: {eml_path}")
            msg = build_message_from_eml(
                from_email=from_email,
                to_email=to_email,
                eml_path=eml_path,
                company_name=company_name,
                extra_attachments=args.attachments or [],
            )
            print(f"  Greeting updated to: Dear {company_name},")
            print(f"  Subject: {msg['Subject']}")
            if args.attachments:
                print(f"  Extra attachments: {', '.join(args.attachments)}")
        else:
            subject, body, html_body = _resolve_message_fields(args)
            msg = build_message(
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                body=body,
                attachments=args.attachments,
                html_body=html_body,
            )
            print(f"  Subject: {subject}")
            if args.attachments:
                print(f"  Attachments: {', '.join(args.attachments)}")

        # ── 4. Send ──────────────────────────────────────────────────────────
        print(f"  Sending via {from_email} …", end=" ", flush=True)
        try:
            send_message(from_email, password, to_email, msg)
            print("sent.")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED.\n  Error: {exc}", file=sys.stderr)
            sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
