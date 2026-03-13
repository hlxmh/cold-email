# Cold Email CLI

A command-line tool that scrapes a company's website for a contact email address, then sends a cold email from your Gmail account — optionally using an existing `.eml` file as the message template with the greeting automatically personalised.

---

## How it works

1. **Scrape** — fetches the target website (and up to 6 internal "contact"-style pages) to find email addresses.
2. **Select** — if multiple addresses are found, you pick which one to send to (or send to all).
3. **Compose** — either re-sends an existing `.eml` file or builds a new message from a subject/body you provide.
4. **Personalise** — replaces the `Dear <old name>,` greeting with the company name you specify.
5. **Send** — delivers via Gmail SMTP using an App Password.

---

## Setup

### 1. Install dependencies

```bash
cd cold-email
python3 -m venv .venv
source .venv/bin/activate
pip install --index-url https://pypi.org/simple/ -r requirements.txt
```

### 2. Create a Gmail App Password

Your regular Gmail password won't work — Google requires an App Password for SMTP access.

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Sign in and click **Create**
3. Name it (e.g. "cold-email") and copy the 16-character password shown

> **Note:** 2-Step Verification must be enabled on your Google account first.

### 3. Configure credentials (optional)

Copy `.env.example` to `.env` and fill in your details:

```bash
cp .env.example .env
```

```ini
GMAIL_EMAIL=you@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
```

If you skip this step, the app will prompt for your password on the first run and save it to `.env` automatically.

---

## Usage

### Basic — send using an `.eml` template

**macOS/Linux:**
```bash
python main.py \
  --from-email you@gmail.com \
  --website https://targetcompany.com \
  --eml-file "My Email.eml" \
  --company-name "Target Company"
```

**Windows (Command Prompt):**
```cmd
python main.py ^
  --from-email you@gmail.com ^
  --website https://targetcompany.com ^
  --eml-file "My Email.eml" ^
  --company-name "Target Company"
```

### Multiple websites/companies in one command

Send to multiple companies with different websites in a single run using `--pairs`:

**macOS/Linux:**
```bash
python main.py \
  --from-email you@gmail.com \
  --eml-file "My Email.eml" \
  --attachments resume.pdf \
  --pairs \
    https://company1.com "Company 1" \
    https://company2.com "Company 2" \
    https://company3.com "Company 3"
```

**Windows (Command Prompt):**
```cmd
python main.py ^
  --from-email you@gmail.com ^
  --eml-file "My Email.eml" ^
  --attachments resume.pdf ^
  --pairs ^
    https://company1.com "Company 1" ^
    https://company2.com "Company 2" ^
    https://company3.com "Company 3"
```

The greeting (`Dear Company Name,`) and personalisation happen automatically for each company. All other options (subject, body, attachments) are shared and sent to each recipient.

### With extra attachments

Attach local files on top of any files already embedded in the `.eml`:

**macOS/Linux:**
```bash
python main.py \
  --from-email you@gmail.com \
  --website https://targetcompany.com \
  --eml-file "My Email.eml" \
  --company-name "Target Company" \
  --attachments portfolio.pdf resume.pdf cover_letter.pdf
```

**Windows (Command Prompt):**
```cmd
python main.py ^
  --from-email you@gmail.com ^
  --website https://targetcompany.com ^
  --eml-file "My Email.eml" ^
  --company-name "Target Company" ^
  --attachments portfolio.pdf resume.pdf cover_letter.pdf
```

### Compose inline (no .eml file)

**macOS/Linux:**
```bash
python main.py \
  --from-email you@gmail.com \
  --website https://targetcompany.com \
  --company-name "Target Company" \
  --subject "Summer Internship Interest" \
  --body-file email_body.html \
  --attachments resume.pdf
```

**Windows (Command Prompt):**
```cmd
python main.py ^
  --from-email you@gmail.com ^
  --website https://targetcompany.com ^
  --company-name "Target Company" ^
  --subject "Summer Internship Interest" ^
  --body-file email_body.html ^
  --attachments resume.pdf
```

### Dry run — preview found addresses without sending

**macOS/Linux:**
```bash
python main.py \
  --website https://targetcompany.com \
  --dry-run
```

**Windows (Command Prompt):**
```cmd
python main.py ^
  --website https://targetcompany.com ^
  --dry-run
```

---

## All options

| Flag | Short | Description |
|------|-------|-------------|
| `--from-email` | `-f` | Your Gmail address. Can also be set via `GMAIL_EMAIL` in `.env`. |
| `--password` | `-p` | Gmail App Password. Can also be set via `GMAIL_APP_PASSWORD` in `.env`. Prompted securely if omitted. |
| `--website` | `-w` | URL of the company website to scrape for contact emails. Mutually exclusive with `--pairs`. |
| `--company-name` | `-n` | Company name used in the `Dear <name>,` greeting. Prompted interactively if omitted. Not used with `--pairs`. |
| `--pairs` | | Multiple (website, company name) pairs for batch sending: `--pairs url1 company1 url2 company2 ...`. Mutually exclusive with `--website`. |
| `--eml-file` | `-e` | Path to a `.eml` file to use as the message template. Subject, body, and embedded attachments are all preserved. |
| `--subject` | `-s` | Email subject line (inline mode only). |
| `--body` | `-b` | Email body as a plain-text string (inline mode only). |
| `--body-file` | | Path to a `.txt` or `.html` file to use as the body. `.html` files are sent as HTML automatically. |
| `--attachments` | `-a` | One or more local file paths to attach. Works with both `--eml-file` and inline mode. |
| `--html` | | Treat `--body` / `--body-file` as HTML markup. |
| `--max-pages` | | Maximum number of pages to crawl when searching for emails (default: `6`). |
| `--dry-run` | | Scrape and print found addresses without sending anything. |

---

## How to export a `.eml` file

**Gmail (browser):** Open the email → ⋮ menu → **Download message** → saves as `.eml`

**Apple Mail:** Open the email → **File → Save As** → Message Format

**Outlook (desktop):** Drag the email from your inbox onto the Desktop or a Finder folder

---

## Project files

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point |
| `scraper.py` | Website crawler that finds email addresses and company names |
| `mailer.py` | Builds MIME messages and sends via Gmail SMTP |
| `requirements.txt` | Python dependencies |
| `.env.example` | Credential template — copy to `.env` |

---

## Troubleshooting

**Port 587 blocked / connection stalls**
Corporate and university networks often block outbound SMTP. Connect to a personal Wi-Fi network or mobile hotspot and try again.

**`SMTPAuthenticationError`**
Make sure you're using an App Password (16 characters, no spaces), not your regular Gmail password.

**No emails found on website**
Some sites load contact info via JavaScript (which the scraper can't execute). Try passing the company's direct `/contact` page URL instead:
```bash
--website https://targetcompany.com/contact
```
