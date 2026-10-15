# SAGE PILOT

Flask database workspace with the welcome message **Sage data pilot**. The
cream, brown, and terracotta interface contains a database selector, table
sidebar, conversation area, charts, business analysis, and downloadable reports.
The sidebar and browser icon use the supplied decorative monogram in its
original gold colour, with a transparent background.

The collapsible sidebar includes recent conversations, optional voice input,
and **Read responses aloud**, with the footer **Created by Philip John / All
rights reserved 2026**. Recent chats are limited to the last 20 known conversation
IDs in the same browser session; they are never listed across other visitors.
Conversations created before history tracking cannot be recovered automatically
unless they are still the active conversation in that browser.

Voice input requires browser support and microphone permission. It only fills
the question box: review the transcript before selecting Run. Recognition may
use your browser vendor's online speech service; this server does not receive
or store audio. Read-aloud uses the browser's speech synthesis, is off by
default, and only reads new answers when enabled.

## Run

```bash
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python app.py
```

Open http://localhost:8502. MySQL 8+ and Python 3.9+ are required.
Configuration comes from [.env](.env), which overrides shell variables and is
reread on requests. The local installation uses `/tmp/mysql.sock`; Workbench
does not need to remain open. Port 8501 belongs to a different application.

## Database access

- The sidebar lists all accessible non-system databases and tables.
- Select a database to focus questions, or select **All databases** for
  cross-database questions.
- Click a table to see its columns, types, keys, references, total row count,
  and actual values. Previous/Next navigation provides access in 50-row pages.
  Table browsing does not truncate individual text cells; responses larger
  than 2 MB are rejected with a request to select narrower columns.
- Names, emails, identifiers, and other ordinary table values are restored.
  They are no longer automatically anonymized. Existing saved masked reports
  are immutable: generate a new report to use restored values.
- Credentials, password/token columns, application secrets, generated SQL,
  prompts, and raw connection errors remain private. Credential aliases and
  derived expressions are checked as well.
- AI analysis still uses bounded results: up to 200 rows, 2,000 characters per
  cell and about 40,000 characters of row data. Charts show up to 20 rows;
  PDF previews show up to 10 rows and 6 columns, with limits disclosed.
  These report limits do not restrict the paginated table browser.

**Public access exposes the actual table values, including personal and business
data.** Questions and bounded results are sent to your configured Azure endpoint.
Only publish databases approved for this use. Keeping configuration hidden does
not make a website unhackable.

Read-only transactions, SELECT parsing, a query timeout, and request limits
remain enforced. Use a dedicated **SELECT-only MySQL account** rather than an
administrator account for public deployment. No delete/update/write operation
is exposed by the application.

## Reports and Gmail

Use **Analyze & report**, then **Preview business report**. The preview works
without a browser PDF plugin; **Download PDF** downloads the saved report.
Statistics describe the returned query result. AI business suggestions should
be independently checked before important decisions.

Set these privately in [.env](.env):

| Setting | Value |
| --- | --- |
| `OWNER_PASSWORD` | Unique password of at least 16 characters |
| `SMTP_USERNAME` | Your Gmail address |
| `SMTP_APP_PASSWORD` | Google app password, not your normal account password |

`GMAIL_USERNAME` and `GMAIL_APP_PASSWORD` are also accepted. Non-empty `SMTP_`
settings take precedence over the corresponding `GMAIL_` aliases. No credential
values need to be copied into chat.

Enable Google 2-Step Verification and obtain an
[app password](https://support.google.com/accounts/answer/185833).
Visit `/owner`, sign in, generate a report, preview it, and click
**Send to my Gmail**. Only the owner can send email. Delivery uses verified
STARTTLS to `smtp.gmail.com:587`; recipients cannot be supplied by public users.
The saved PDF is attached without regeneration. Duplicate sends are blocked;
an uncertain SMTP acknowledgement requires checking Gmail before another attempt.

## Temporary public access

```bash
cloudflared tunnel --url http://127.0.0.1:8502 --no-autoupdate
```

The resulting HTTPS URL is public and temporary. The Mac, MySQL, Flask, and
tunnel must remain running. Cloudflare proxies the traffic. This setup is for
demonstration, not permanent production hosting. Keep the Flask listener on
loopback because proxy headers are trusted for this local-tunnel arrangement.

Conversations and reports are scoped to individual browser sessions. Private
SQLite storage under `instance/` is excluded from source control. Records older
than seven days are removed when an analysis completes. New chat starts a
separate conversation. Analysis limits are 5/minute per client, 30/minute shared,
and 200/day shared. Owner login and email have additional limits.

## Tests

```bash
.venv/bin/python -m pip install --only-binary=:all: -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```
