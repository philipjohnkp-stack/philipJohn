# SAGE PILOT

Flask chat-based database assistant with the welcome message **Sage data pilot**.
The cream, brown, and terracotta interface contains a conversation area, charts,
business analysis, and downloadable reports. Database connections and schema
discovery are used internally; database objects are not displayed in the UI.
The sidebar and browser icon use the supplied decorative monogram in its
original gold colour, with a transparent background.

Use the **Appearance** selector at the top right: **Auto**, **Light**, or **Dark**.
A sun icon indicates the active light theme and a moon indicates the active dark
theme, including when Auto switches between them.
Auto is the new default (including for visitors who used the old toggle): light
from 7:00 AM until 7:00 PM and dark otherwise, based on the visitor's device clock
and local timezone, without location permission. Open pages switch at the next
boundary and recheck at least every minute while active, and when revisited.
Manual Light/Dark choices override the schedule until Auto is selected again.
The preference is saved in this browser for the current site address and shared
with the owner sign-in page and other open tabs. If browser storage is blocked,
the selector still works for the current page and displays a notice. Report previews
follow the theme; charts retain a light canvas for readable labels, and exported
PDFs and email attachments keep their original print-friendly colours.

The collapsible sidebar includes recent conversations, optional voice input,
and **Read responses aloud**, with the footer **Created by Philip John / All
rights reserved 2026**. Recent chats are limited to the last 20 known conversation
IDs in the same browser session; they are never listed across other visitors.
Conversations created before history tracking cannot be recovered automatically
unless they are still the active conversation in that browser.

**Delete history**, beneath Recent chats, opens a confirmation dialog. Confirming
permanently removes the conversations currently tracked by this browser session
(up to 20) and their saved reports from local storage, then starts an empty chat.
It does not affect other visitors, MySQL records, previously downloaded PDFs,
sent emails, application settings, or usage limits. Untracked older conversations
are not identifiable from this session and remain subject to normal retention.
Active answers or email sends must finish before deletion. Cancel leaves history
unchanged; simply asking the chatbot to delete history does not perform deletion.

The full-width header displays the original gold monogram with a clockwise
correction for its built-in tilt, alongside the Sage name. Rounded **Quick
answer** / **Analyze data** mode controls sit above the conversation; recent
chats and voice controls remain in the collapsible left sidebar.
Quick answer retains chat; Analyze Data displays the latest analysis as an
executive dashboard with the answer, supported numeric KPI cards, available
chart, findings, and PDF/email controls. The conversation trail remains visible
in both modes, including after switching modes or reloading the same conversation.
Metrics come only from returned values;
no example KPIs or inferred totals are added. The active tab is terracotta
(`#B54834`), the inactive Analyze Data tab is champagne gold (`#C7A46A`),
and the workspace background is warm ivory (`#F7F3EE`).

Voice input requires browser support and microphone permission. It only fills
the question box: review the transcript before selecting Run. Recognition may
use your browser vendor's online speech service; this server does not receive
or store audio. Read-aloud uses the browser's speech synthesis, is off by
default, and only reads new answers when enabled.
Both voice controls show **ON/OFF** indicators in light and dark mode. The
microphone highlights only while recording and returns to OFF when recording
ends or fails. The read-aloud switch and indicator show whether automatic
playback of new answers is enabled, not whether audio is currently playing.

Pasting copied text into the question box uses the original clipboard text,
even when the clipboard also contains an image. Image-only PNG snips are read
before Run can submit them. Local OCR composites transparency onto white and
retries an empty result at double size within the image pixel limit; it does
not silently switch to external AI when local recognition finds nothing.
If local OCR dependencies are absent, the existing Azure vision fallback is
used. An unreadable snip displays an error instead of submitting an empty
question. Remove it or paste the original text to continue. Failed requests
retain the draft and snip for retry; image previews are not saved workbook files.

## VS Code MCP server

The project includes a local stdio MCP server for database tools. Open this
folder in VS Code with the MCP extension enabled; VS Code reads
`.vscode/mcp.json` and starts the server automatically. Install project
dependencies into `.venv` first with
`./.venv/bin/python -m pip install -r requirements.txt`.

The server reads its database connection settings from `.env VS CODE`, falling
back to `.env` if that file does not exist. It requires `DB_HOST`, `DB_PORT`,
`DB_USER`, and `DB_PASSWORD`; the Azure OpenAI settings are not needed. Use a
dedicated MySQL account granted read-only access to only the intended databases.
The MCP tools expose accessible schema metadata and one read-only query tool.
Queries are restricted to a single schema-qualified `SELECT`, capped at 200
rows, and private-looking result fields and values are redacted. The server
enforces read-only queries, but database permissions should also be read-only.

## Local Sage SQL workspace

MySQL Workbench is a client; it does not need to be installed into Sage. When
MySQL Server and Sage both run on this Mac, start the local-only Sage app with
`./.venv/bin/python local_app.py` and open `http://127.0.0.1:8502`. The app binds
to loopback and rejects nonlocal requests; it is not reachable from Azure or
other devices.

The local app uses the existing `.env` database credentials but connects only
to `127.0.0.1` on the configured MySQL port; it ignores the Unix-socket setting.
It only exposes `messy_employees` and `co-pilot employees`, checks MySQL grants
on each connection, and rejects accounts with privileges beyond the configured
read-only scope. The Azure private app remains unchanged and keeps requiring
verified TLS over a network connection. Local and Azure modes must not be
combined.

## Excel analysis

### Generic private workspace (separate deployment)

Set `PRIVATE_APP=true` only on a **separate** App Service, with its own
`STORE_PATH`, Microsoft application registration, and private storage. Do not
enable this on the public synthetic demo; `DEMO_MODE=true` and `PRIVATE_APP=true`
are mutually exclusive. The public app's default UI and sources are unchanged.

The private workspace accepts different `.xlsx` workbooks and lets you choose
their visible worksheets. It does not require a database or AI credentials for
supported local counts and aggregates. **General / SQL help** is the default
conversation source: it explains SQL, Excel formulas, and general topics without
executing queries or reading workbooks. Select a worksheet or configured database
for actual data analysis. Each source has a separate conversation history.
General help, more complex Excel questions, and all database AI requests require
per-question permission. The private UI explains
which context and results may be sent to Azure OpenAI. Pattern masking is not
complete anonymization; only use data approved for that service.

General help and pasted SQL review use one AI request without a classification
round trip. Local Excel counts and aggregates use zero AI requests. Private
database questions discover the schema once per answer; account privileges and
TLS are still checked on each connection. `answer.timing` logs record elapsed
milliseconds and AI call/time totals without recording questions or results.
Response times depend on workload, network, and the configured AI deployment.

**Microsoft authentication must be configured before this app can be used:**

1. Register a single-tenant Microsoft Entra application and configure Azure App
   Service Authentication (Easy Auth) to require authentication on every route.
   Use the v2 issuer for that tenant, enable the token store, and restrict access
   to the intended user. Configure its callback URL for the **private** app.
2. Set `PRIVATE_TENANT_ID`, `PRIVATE_CLIENT_ID`, and `PRIVATE_OWNER_ID` to the
   tenant UUID, application/client UUID, and that user's object UUID in the tenant
   (not an email address). Empty/invalid settings leave the workspace locked.
3. The app independently verifies the signature, issuer, audience, expiry,
   tenant, and owner of the Microsoft ID token provided by Easy Auth in
   `X-MS-TOKEN-AAD-ID-TOKEN`. A forged identity header or local owner password
   cannot bypass this check. Expired tokens require renewed Microsoft sign-in.
   No credentials should be submitted through the chat.

Private pages use `Referrer-Policy: same-origin` so Easy Auth can validate
cookie-authenticated uploads and other POST requests. Cross-origin requests
still receive no referrer. Do not override this with `no-referrer` at a proxy:
Azure can reject valid same-site POSTs with an empty HTTP 403 response.
Application CSRF tokens and Microsoft identity checks remain required.

See Microsoft's [token header and token-store documentation](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-oauth-tokens).
For Azure, store application secrets using Key Vault references and managed
identity; do not package `.env` or put secrets in source control. Microsoft
authentication, Key Vault, and networking are deployment prerequisites, not
resources automatically created by setting `PRIVATE_APP`.

**Uploads:** one `.xlsx` file at a time, max 20 MB compressed, 100 MB expanded,
20 worksheets, 128 columns, and one million declared cells per workbook.
Macros, embedded binary objects, and linked workbooks are rejected. At most ten
active workbooks are retained. The workbook is stored inside the private
instance's session SQLite database, never in the static/public directory.
Use encrypted persistent Azure storage for `STORE_PATH` and restrict platform
backup/access permissions. The app itself does not encrypt that database file.
Temporary analysis copies are removed when the request finishes.

Workbooks and their associated saved chats/reports expire after **24 hours from
upload**. They cannot be selected or analyzed after expiry. Secure SQLite
deletion runs on each authenticated request, at startup, and every minute while
the app runs; an offline app removes overdue files when it next starts. Platform
backups/snapshots require a matching retention policy separately. Manual deletion
removes the workbook and all associated worksheets/chats/reports. Already
downloaded exports and sent emails cannot be recalled.

**Optional database:** leave `PRIVATE_DATABASE_ENABLED=false` until the server
is ready. Enabling it requires either `PRIVATE_DB_NAME` for one database or
`PRIVATE_DB_NAMES` containing a JSON array of database names, and existing `DB_*` settings
with `DB_REQUIRE_TLS=true` and no local socket. Configure them server-side;
there is no public connection-string input. Different deployments can target
different MySQL/MariaDB databases without code changes. Other database engines
and automatic cross-workbook joins are not supported.

For example, `PRIVATE_DB_NAMES='["sales","quality records"]'` allows only those
two databases, including cross-database SELECT queries. Leave `PRIVATE_DB_NAME`
empty when using this setting. Empty, duplicate, invalid, and system database
names are rejected. Every configured database must be accessible; a missing
database fails explicitly rather than silently returning a partial scope.

Use a dedicated account with direct `SELECT` and optional `SHOW VIEW` grants on
only the chosen databases/tables (plus MySQL's `USAGE`). Each configured database
must have a SELECT grant. Global reads, write/admin
privileges, role grants, and grant options are refused; this intentionally rejects
unclear grants rather than assuming they are safe. The connector checks grants
before querying and restricts SQL to the configured schemas. An administrator must
create the least-privilege account. For database-level grants, escape `_` and `%`
in the database name because MySQL can treat them as wildcards; for example,
``GRANT SELECT ON `sales\_records`.* TO ...``. Exact table-level grants are also
accepted. Ambiguous unescaped database-level wildcard grants are rejected, even
on servers whose `partial_revokes` setting would make them literal.
Configure App Service VNet integration and
the database's private endpoint/private DNS, disable public database access, and
test connectivity before enabling it. An app setting alone does not establish a
private network or migrate a Workbench database.

For a database kept on a local computer, use an approved private VPN with routing
from the App Service integration subnet to that computer. Keep the computer and
VPN online, restrict MySQL TCP access to the approved private route, and verify
the server's TLS certificate using `DB_SSL_CA` when a private CA is needed.
Do not forward public port 3306 or transfer a local Unix socket path to Azure.
Workbench remains a separate client; keep its administration account separate
from Sage's read-only account. A database export is a snapshot, not a live VPN connection.

The standard web application is now database-only. The "Analyze from" selector
and workbook discovery are removed from the UI. New conversations use MySQL;
old Excel conversations are not restored or listed, but their stored data is
not deleted. The Excel connector below remains available for internal use and
tests with the application-factory configuration `ENABLE_EXCEL=True`; it is
disabled by default and has no source selector in the standard UI.

### Direct answers, privacy, and response time

Sage answers the requested calculation first, without generic business advice.
On a new Excel conversation, these standalone questions are calculated locally:
`How many records?`, `Sum Amount`, `Average Amount by Region`, and
`Calculate total sales by region and save the results to Excel.`
`minimum`, `maximum`, and exact column names (spaces become underscores) are also
supported. For `sales`, the local path uses an exact `Sales` column or a single
unambiguous `Amount`, `Sales_Amount`, or `Total_Sales` column. Numeric aggregates
require numeric data. These requests use all rows/dates in the imported table,
respect existing footer exclusion, and make **zero external AI requests**.
Results remain available through the existing PDF/Excel download controls;
Sage does not save a file onto the visitor's device automatically.

Filters, comparisons, ambiguous metrics, and contextual follow-ups are not
guessed by the local fast path. **External AI is off by default for Excel.**
For these requests, review the notice and select **Allow external AI for this
question** before Run. Permission is checked server-side, applies only to that
request, and is not saved with the conversation. The checkbox resets after a
submission. Without permission, unsupported requests produce an actionable
message instead of silently contacting AI or switching to MySQL.

The source selector discovers workbook and visible sheet names in the configured
Excel folder; this metadata discovery is not limited to the selected workbook.
Worksheet records used for analysis come only from the selected sheet.
With external AI enabled, Azure OpenAI may receive the question, recent chat
context, selected sheet's column names, warnings, and bounded query results.
The original workbook is not uploaded. Excel still masks credential fields before
results are shown or sent onward; other worksheet values can remain. Database
questions do not show an external-processing caveat and do not use the Excel-only
consent checkbox. The public demo uses fictional records only and removes
credentials and personal identifiers from text before an Azure OpenAI request.
Voice recognition has its separate browser service notice. These changes do not
constitute a private-cloud deployment, an enterprise security certification, or
an AI-provider retention guarantee.

Excel responses state whether they were calculated locally or used external AI.
Application logs include `answer.timing` with elapsed milliseconds, AI-call count,
and total AI-call time, without question text or returned business values in that
timing event. Measure representative workloads before setting latency targets:
network, workbook size, AI inference, and concurrency vary; 300 ms is not a
guarantee. Missing files, denied access (which may be a lock), and renamed or
hidden sheets report specific next steps. An open Excel workbook is not assumed
to be locked if it can still be read.

Set `EXCEL_DATA_DIR` privately in `.env` to the approved Excel folder. On this Mac,
the background service cannot access Desktop under macOS privacy restrictions.
The local installation therefore uses imported copies in `instance/excel`, with
private folder/file permissions, rather than changing OS permissions. The originals
are in Desktop **DATA FILES / DATA ANALYSIS / EXCEL DATA ANALYSIS**
(the DATA ANALYSIS folder name has a trailing space).
Only direct `.xlsx` files are read;
Office lock files, hidden sheets, symlinks, macros and external links are not used.
Paths are never accepted from public requests or exposed to the AI or browser.

Select a workbook/worksheet under **Analyze from**. Changing the source starts a
separate conversation; recent chats restore their original source. Database
analysis stays available and does not silently mix with Excel. Excel queries do
not connect to MySQL, although the existing application's configuration is still
required. Files in the configured folder are reread on the next question.
**Desktop changes are not automatically synchronized.** After saving changes in
Excel, explicitly refresh the imported copies using:

```bash
.venv/bin/python excel_assistant.py "/Users/philipjohn/Desktop/DATA FILES/DATA ANALYSIS /EXCEL DATA ANALYSIS" --replace
```

For a first import, omit `--replace`. Only imported copies are replaced.
Workbooks removed from Desktop are not automatically removed from the import
folder; remove their imported copies separately if they should no longer be available.

The connector inspects workbook structure with openpyxl, then reads the selected
sheet/range into a **pandas DataFrame using `read_excel(..., engine="openpyxl")`**,
cleans blanks, dates, cached formulas and Excel errors, and uses a temporary
in-memory SQLite table (no changes to the workbook or MySQL). It reads the first
contiguous header/data block, scanning
the first 25 rows for a header. A repetition of the first heading starts a
side-by-side table and ends the first block; other duplicate headings get numbered suffixes.
Dates become ISO dates; blanks remain NULL; percentages remain fractions.
The report states the exact imported range. Recognized total/average footers are
excluded with a notice to prevent double-counting. Separate blocks after blank rows,
side-by-side exercises, and decorative dashboard areas are not combined.
Select a raw-data sheet rather than a presentation/pivot sheet for full analysis.
Limits: 30 workbooks, 20 MB per file, 100 MB expanded, 128 columns and one million
cells per sheet. Oversized, missing, encrypted or invalid files produce an error.

Saved Excel formula results are used, not recalculated. Missing formula caches
and Excel error cells become NULL with an explicit report warning. Recalculate
and save in Excel before asking about changed formula results. Conditional
totals/counts/averages, grouping, rankings and CASE-based conditions run on the
full imported table; results sent to AI/reports keep the existing 200-row and
serialization limits.

Open PDF options and choose **Download Excel results** to explicitly export a
new workbook containing Analysis and Results sheets. No source file is overwritten
or edited, and cell text is exported as text, never an executable formula.
PDFs, charts, email preview/send controls and session-history deletion still work.
Exports reflect bounded returned results, not a copy of the whole workbook.

Example: select **Intermediate_Practice.xlsx.1 / Sales**, then ask
“What are total sales, number of sales, and average sale amount for North?”
The supplied workbook's saved data gives **4,000**, **3**, and **1,333.33**.
An all-region grouped total is **13,100**.

The supplied “Excel Conditional Functions and Chatbot” procedure informs the
read/validate/analyze/export workflow. Original workbook write-back and automatic
Excel/MySQL joins are intentionally not enabled: they require an explicit
mapping and separate write authorization. The other course documents are not
imported as data or instructions.

**Public exposure:** anyone able to access Sage can select these approved Excel
sheets and request their data. Only place approved data in this folder. Bounded,
credential-protected results go to the configured Azure AI service; do not put
private workbooks here for a public deployment.

## Starting the app

```bash
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python app.py
```

Open http://localhost:8502. MySQL 8+ and Python 3.9+ are required.
Configuration comes from [.env](.env), which overrides shell variables and is
reread on requests. The local installation uses `/tmp/mysql.sock`; Workbench
does not need to remain open. Port 8501 belongs to a different application.

## Mac-hosted public access

This Mac's fixed ngrok address is https://doorman-showplace-unedited.ngrok-free.dev.
The authenticated ngrok Dev Domain replaces temporary anonymous Cloudflare links.
The free plan may show a browser warning page and applies account usage limits.

User LaunchAgents in `~/Library/LaunchAgents/com.sagepilot.app.plist` and
`~/Library/LaunchAgents/com.sagepilot.ngrok.plist` start Sage and the fixed
tunnel at login and restart either process if it exits. These are local machine
settings, not repository files. Logs are in `~/Library/Logs/SagePilot/`.
Ngrok credentials are stored privately in
`~/Library/Application Support/ngrok/ngrok.yml`, not in the service definitions.
HTTP request inspection is disabled to avoid retaining database payloads there.

The Mac must remain awake, online, and logged in; MySQL must also be running.
These services do not provide hosted 24/7 availability or bypass ngrok limits.
No system sleep settings are changed. To stop public access for the current
login session, run:

```bash
launchctl bootout "gui/$(id -u)/com.sagepilot.ngrok"
```

To restore it, run:

```bash
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.sagepilot.ngrok.plist"
```

## Database access

- Simple general questions are answered directly from model knowledge without
  accessing MySQL. Questions about your records use the connected databases.
  Live web search is not connected; current facts cannot be verified.
  Follow-up questions reuse details already supplied in the conversation;
  clarification is only needed for essential information still missing.
- Named-person and identifier lookups automatically search relevant tables in
  the connected databases, without asking users to select a database or table.
  Answers keep differing records separate; a name alone does not establish
  that records refer to the same person. Aggregate results from matching datasets
  remain separate rather than being added together.
  Person, location, and measure columns are resolved internally from the schema;
  column-mapping questions are blocked and replanned once. Short follow-ups
  retain the original request and answered choices. Saying "amount" does not
  authorize assuming `amount > 0`; truly unresolved sales definitions still
  require a business-language clarification rather than an invented condition.
  Repeated table names are resolved internally across matching databases, including
  when a follow-up names a table. Sage does not ask visitors to choose hidden
  database/schema names. It uses neutral source labels to distinguish returned
  records and counts, respects explicit source restrictions, and asks only for
  essential missing business details (such as a date range or metric definition).
- Database access is internal to answering questions. The UI does not expose
  database selectors, schema/table navigation, column details, or raw result
  tables. Returned values may be used in natural-language answers, dashboards,
  charts, and reports. Generated answer/report text and chart labels omit
  recognized physical database and table names; chart titles are generic.
- Credentials, password/token columns, application secrets, generated SQL,
  prompts, and raw connection errors remain private. Credential aliases and
  derived expressions are checked as well.
- AI analysis still uses bounded results: up to 200 rows, 2,000 characters per
  cell and about 40,000 characters of row data. Charts show up to 20 rows.
  Raw returned rows and database structure are not included in public report
  responses or PDFs.

**Public access exposes the actual table values, including personal and business
data.** Questions and bounded results are sent to your configured Azure endpoint.
Only publish databases approved for this use. Keeping configuration hidden does
not make a website unhackable.

Read-only transactions, SELECT parsing, a query timeout, and request limits
remain enforced. Use a dedicated **SELECT-only MySQL account** rather than an
administrator account for public deployment. No delete/update/write operation
is exposed by the application.

## Optional PDFs and email

**Quick answer** is the default. **Analyze data** shows additional findings.
Both offer a PDF document icon beside the answer. PDFs are only generated
when requested, not automatically during chat. Downloads and email attachments
are named `Sage Analyse Report.pdf`. Open the icon to preview the
answer, choose **No chart**, **Bar chart**, or **Line chart**, and download.
Chart options are available only when the result has comparable numeric values.
The preview works without a browser PDF plugin.
Report titles are uppercase. PDF titles and section headings use champagne gold
(`#C7A46A`), matching the preview and the inactive Analyze Data tab. Dashboard
report titles use the same styling. PDFs include report prose and an optional
chart, not a table of raw returned rows.
Statistics describe the returned query result. AI business suggestions should
be independently checked before important decisions.

Simple count answers omit repetitive findings, generic business actions, and
technical scope warnings. Counts from separate sources are not added together.
They are formatted directly from the query result, avoiding an extra AI report
call. Explicit analysis requests still use the model, and truncated results
retain their warning.

The envelope icon beside each answer (and in the executive dashboard) opens
the PDF options and focuses the recipient field. Enter your email address and
select **Send PDF by email**. Sage sends the PDF attachment directly from the
configured Gmail account with the selected chart. No owner sign-in, recipient
verification, email app, or manual attachment is required.

Public direct sending is limited to three attempts per hour per browser session
and client address, three per recipient per day, and site-wide totals of 20 per
hour and 50 per day. Limits use fixed time buckets, so they reset at bucket
boundaries. Recipients are hashed for rate limiting, not stored as plain text.
These limits reduce abuse but do not authenticate visitors or prove that they
own the entered email address; the configured sender can receive complaints or
provider restrictions. Do not enter an address without permission.

The site owner must configure Gmail delivery once:

Set these privately in [.env](.env):

| Setting | Value |
| --- | --- |
| `OWNER_PASSWORD` | Unique password of at least 16 characters |
| `SMTP_USERNAME` | Your Gmail address |
| `SMTP_APP_PASSWORD` | Google-generated 16-character app password, not your normal account password |

`GMAIL_USERNAME` and `GMAIL_APP_PASSWORD` are also accepted. Non-empty `SMTP_`
settings take precedence over the corresponding `GMAIL_` aliases. No credential
values need to be copied into chat.

Enable Google 2-Step Verification and obtain an
[app password](https://support.google.com/accounts/answer/185833).
Set `SMTP_USERNAME` to the same Gmail account that generated the app password.
Google displays the app password with spaces; Sage removes spaces automatically.
Gmail delivery uses `smtp.gmail.com:587` with STARTTLS and verified certificates,
and retries on `smtp.gmail.com:465` with verified implicit TLS if Gmail disconnects
during authentication. The app validates app-password length before connecting
and logs the failed SMTP stage and response code without logging credential values
or raw server response text.
`OWNER_PASSWORD` is only needed for the separate owner sign-in, not public email
delivery. Ask a question, open its PDF or email icon, enter one recipient,
select the chart option, and click **Send PDF by email**. Delivery uses verified
STARTTLS to `smtp.gmail.com:587`, with Gmail's hostname supplied for certificate
verification.
The PDF is generated with the selected chart and attached automatically; no
email app or manual attachment is needed. Duplicate sends are blocked per report,
even if the recipient or chart is changed;
an uncertain SMTP acknowledgement requires checking Gmail before another attempt.

## Application logs

The application writes structured logs to `logs/app.log` and rotates the file
at 10 MB, retaining up to five backups. Entries include timestamps, an owner or
anonymous user label, a pseudonymous session ID, action, status, and error
details. Report generation, PDF/chart exports, email requests, SMTP outcomes,
and application exceptions are logged. Configured passwords, API keys, tokens,
and other credential values are redacted; recipient addresses and question
contents are not logged.

Set `APP_DEBUG=true` in `.env` for additional request and process/thread detail.
This enables detailed application logging only; it does not enable Flask's
interactive debugger. Keep the `logs/` directory private and do not serve it
from a public static path.

## Deploy to Azure App Service (Canada Central)

Use a Linux App Service with Python 3.12 in **Canada Central (Toronto)**,
one Basic B1 instance, and startup command `sh startup.sh`. Do not fall back to
another region if subscription quota or capacity prevents creation.
The existing GitHub Actions workflow runs the test suite but does not deploy.
No Render service is needed; the legacy Blueprint below is an alternative only.

Create a clean ZIP locally using the explicit deployment-file allowlist:

```bash
sh package-azure.sh "$TMPDIR/sage-pilot-deployment.zip"
```

The output must not already exist. This includes current local application
changes, not just committed files, and excludes environment files, Git metadata,
local tooling, logs, databases, reports, and workbooks. Review and test local
changes before deployment. Do not upload the entire workspace.

### Public synthetic-data demo

For the agreed public demo, set `DEMO_MODE=true` and
`DEMO_SQLITE_PATH=/home/sage-pilot/demo.sqlite3` in App Service. The app creates
a small, fictional pharmaceutical quality/regulatory/batch dataset on first
use and queries it through read-only SQLite. The public demo is not connected
to the owner's Workbench and contains no employee data. Existing marked demo
databases remove the temporary synthetic employee fixture from the earlier
deployment on startup. The app refuses to use an existing unmarked SQLite
database. Do not configure MySQL or copy local records for this mode; no
managed MySQL server is needed. The UI labels the data as synthetic.
Set the Azure OpenAI endpoint, key, API version, and deployment privately in
App Service settings; the deployment ZIP contains no `.env` file. Do not enter
confidential information into the public demo.

The demo has no managed database, but the Basic B1 App Service plan is billed
while running. Keep the plan to one instance; its SQLite conversation storage
is not validated for scale-out.

Configure these settings privately in App Service before ZIP deployment:

- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` to install `requirements.txt`.
- `STORE_PATH=/home/sage-pilot/studio.sqlite3` for persistent chat/report storage.
- `EXCEL_DATA_DIR=/home/sage-pilot/excel` for separately approved workbook copies.
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
  `AZURE_OPENAI_API_VERSION`, and `AZURE_OPENAI_DEPLOYMENT_MINI`.
- `DB_HOST`, `DB_PORT=3306`, `DB_USER`, `DB_PASSWORD`,
  `DB_UNIX_SOCKET=` (empty), and `DB_REQUIRE_TLS=true`.
- A strong `OWNER_PASSWORD` of at least 16 characters; optional
  `SMTP_USERNAME` and `SMTP_APP_PASSWORD` for email.

Use HTTPS Only, minimum TLS 1.2, and Always On. Keep the plan at one instance:
SQLite storage and application locking have not been validated for scale-out.
The startup script uses `/home` for persistence; do not move chat storage to
the temporary deployment directory. Back up persistent data separately.

For a non-demo deployment with real MySQL sources, the Mac's MySQL Unix socket
is not accessible from Azure. Provision a Canada Central MySQL Flexible Server
or use an existing approved server there. Use a dedicated SELECT-only
application account, verified TLS, and network rules that limit database access
to the app. Do not enable unrestricted public database access. Confirm database
names and workbook names before copying data; do not migrate MySQL system
schemas, local session history, or secrets. App Service hosting and managed
MySQL have separate ongoing charges.

Upload the ZIP using App Service ZIP deployment (for example,
`az webapp deploy --resource-group GROUP --name APP --src-path ARCHIVE --type zip`
after Azure CLI sign-in). Inspect deployment/build logs, then verify HTTPS,
static assets, database answers, Excel answers, and persistence after restart
before treating deployment as complete. A working landing page alone is not
proof of a working database migration.

**The app is publicly accessible unless a separate access restriction or
App Service Authentication policy is enabled.** Owner sign-in protects owner
actions, not all database/Excel analysis. Before transferring private data,
restrict access to approved users. App Service location does not relocate the
existing Azure OpenAI endpoint; verify its region and processing terms before
claiming Canada-only processing.

## Run with Docker (app + MySQL)

```bash
cp .env.docker.example .env.docker   # Azure OpenAI keys; DB_USER/DB_PASSWORD = read-only account
cp .env.mysql.example  .env.mysql    # MySQL root password, database name, read-only account
docker compose up -d --build
```

Open http://localhost:8000. `docker-compose.yml` runs two containers:

- `sage`: the Flask app (gunicorn on port 8000), built from [Dockerfile](Dockerfile).
  It connects to MySQL at `db:3306`. Logs go to `./logs`, and chat storage
  goes to a named volume.
- `db`: MySQL 8.4, published on host port **3307** so it does not clash with a
  local MySQL. On the first start, scripts in [db/init](db/init) create a sample
  `employees` table and a SELECT-only account (`SAGE_READER_USER`).
  `SAGE_READER_PASSWORD` must match `DB_PASSWORD` in `.env.docker`.

Use MySQL from the command line:

```bash
docker compose exec db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'   # admin
docker compose exec db sh -c 'mysql -u"$SAGE_READER_USER" -p"$SAGE_READER_PASSWORD" "$MYSQL_DATABASE"'  # read-only
mysql -h 127.0.0.1 -P 3307 -u sage_reader -p sage_data   # from the Mac, or MySQL Workbench on 127.0.0.1:3307
```

Other useful commands: `docker compose logs -f sage`, `docker compose down`
(keeps data), and `docker compose down -v` (deletes MySQL data and reruns the
init scripts on the next start). `.env` files are excluded from the image by
[.dockerignore](.dockerignore). This matters because `.env` overrides container
environment variables.

## Deploy to Azure Container Apps (budget)

```bash
cp .env.azure.example .env.azure   # cloud MySQL host + Azure OpenAI; becomes Container App secrets
az login
BUDGET_EMAIL=you@example.com BUDGET_AMOUNT=50 ./deploy-azure-aca.sh
```

[deploy-azure-aca.sh](deploy-azure-aca.sh) does the following:

- Creates `SageRG` in Canada Central and an ACR **Basic** registry.
- Builds the image in ACR with `az acr build`, so local Docker isn't needed.
- Creates a Consumption Container Apps environment with 30-day log retention.
- Deploys the app with 0.25 vCPU / 0.5 GiB and **0 to 1 replicas**. It scales
  to zero when idle and is served over HTTPS by default.
- Pulls the image with a managed identity, so no registry password is stored.
- Stores every setting as a Container App secret.
- Adds a monthly resource-group budget that emails you at 80% of actual spend
  and 100% of forecast spend.

Run the script again to deploy a new image tag. Override names with `RG`, `ACR`,
`APP`, and `LOCATION`.

Cost notes:
- The MySQL container is for local use only. In Azure, point `DB_HOST` at a
  reachable MySQL server, for example Azure Database for MySQL Flexible Server B1ms.
- Scale-to-zero means the first request after an idle period takes a few
  seconds while the app cold-starts.
- Container storage is ephemeral: chat history and sessions reset when the
  replica restarts. Persisting them requires an Azure Files mount, which costs extra.

## Alternative: deploy to Render

The repository includes a Render Blueprint and GitHub Actions test workflow.
Connect this repository to Render as a Blueprint. Render waits for the test
workflow to pass before deploying and attaches a paid persistent disk for
session/report storage. Render generates the public URL after the service starts.

Set the Blueprint's `sync: false` values in Render's private environment settings;
do not commit `.env` or paste credentials into GitHub or chat. Provide the Azure
endpoint/key/deployment, the cloud MySQL host and dedicated SELECT-only user,
`OWNER_PASSWORD`, `SMTP_USERNAME`, and `SMTP_APP_PASSWORD`. The database must be
reachable from Render over TCP; local MySQL sockets are not available there.
TLS certificate verification is enabled for the database connection. If the
provider uses a private CA, set `DB_SSL_CA` to its certificate path in Render.

**Anyone who can access the public app can browse and query the connected
database.** Use only data approved for public access and a SELECT-only MySQL
account. The configured Gmail address remains the recipient; only the signed-in
owner sees the PDF email action.

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
