# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MVP of an NFC/QR review-capture platform for local businesses. `Proyecto_NFC_Review_Analytics.pdf`
holds the original product vision and business model; **[ROADMAP.md](ROADMAP.md) supersedes its
module ordering** and tracks what is actually built.

**Starting a session: read [ROADMAP.md#próximos-pasos](ROADMAP.md) first.** It carries the
current state, the decisions already settled (don't reopen them), what is blocked waiting on the
user, and one open question to ask them before building anything.

**Then read [docs/revision-tecnica-2026-09-03.md](docs/revision-tecnica-2026-09-03.md)** before
touching code. It is the full technical review: findings ranked by severity, each with its fix and
its test; the list of things that are right *and must not be "fixed"*; the recommended order of
work; and the next features. Four findings there break with the first paying client and the test
suite cannot see them (they only appear on Postgres, behind Render's proxy, or in GitHub Actions).
Tick items off in that document as they are resolved.

The product works end to end today: capture flow, per-tenant dashboard behind a login, monthly
report with automatic delivery, client onboarding, migrations, 176 tests. Demo panel:
`demo@cafe.cl` / `demo1234`. Nothing has been deployed or published — the user has not bought the
domain yet, and printing a plaque with a temporary URL is the one irreversible mistake to avoid.

## Constraints that are not negotiable

**1. Never reintroduce "review gating".** The original spec routed 1-3★ away from Google and only
sent 4-5★ there. That violates Google's review policies and can get a client's Business Profile
suspended. The landing page gives every visitor the same one-click path to Google; the private
channel is an always-available *addition*, never a replacement or a gate. There is deliberately
no star selector before the Google button — it added a click (losing reviews, the exact thing
the product sells) and created ToS ambiguity for nothing, since a self-reported star is
unverifiable anyway. Real ratings come from the Google Business Profile API (Module 2).

**2. URLs are physical hardware.** A token in `placements.token` gets burned into an NFC chip and
printed on a plaque that gets glued to a table. It can never change afterwards. This is why
tokens are random and non-enumerable (`models.new_token`), why each physical support is its own
row, and why `BASE_URL` must point at the final owned domain before anything is printed.

**3. Metrics must be defensible, and must agree everywhere.** The conversion rate is the number
a client pays for. It is computed over *unique sessions*, never raw event rows — an earlier
version divided conversions by a denominator that included those same conversions, which capped
the metric at 50%. Bots and page reloads are excluded at write time. Don't "simplify" this by
counting rows. Period filtering lives in SQL (`load_taps(business_id, start, end)`), translating the
business's local-time bounds to UTC — the panel re-queries on a timer, so loading a venue's whole
history to show one month stops being free once a client has been installed for a year.
All of this lives in [app/services/metrics.py](app/services/metrics.py), which is
the single source of truth: the dashboard and the monthly report both read from it so they can
never show different numbers for the same period. Never compute a client-facing metric inline.

**4. Time is bucketed in the business's local timezone, never UTC.** Events are stored in UTC
(enforced by the `UtcDateTime` column type — SQLite silently drops offsets, Postgres does not,
and that divergence produces subtly wrong numbers), but every report and chart groups by local
day and month. A restaurant's dinner service falls after midnight UTC: bucketing in UTC split
one evening across two days and pushed the last day of the month into the next month's report.
`TIMEZONE` is global today because every client is Chilean; it becomes a `Business` column the
day one isn't.

**5. $0/month is a validation-phase choice, not an architectural principle.** See ROADMAP.md —
sleeping free tiers are incompatible with a customer standing at a counter waiting for a page.

## Commands

```powershell
# The project's dedicated virtualenv (created from scratch; do not reuse any other env)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Seed the demo business + its placements; prints every placement URL, its QR path,
# and the owner's dashboard link (tokens are random, so re-read this output — the
# URLs change every time the DB is recreated)
python -m scripts.seed_demo_business

# Fill the DB with ~2.5 months of realistic traffic so the dashboard and report
# look like a real venue (a report with 4 visits demos nothing)
python -m scripts.seed_demo_data --limpiar

# Write a month's report to informes/ (HTML by default, --pdf needs WeasyPrint)
python -m scripts.generate_report --mes 2026-08

# Onboard a real client: creates the business, its placements and their QRs
python -m scripts.new_client              # interactive; --listar recovers lost tokens
uvicorn app.main:app --reload
```

`scripts/new_client.py` is the operator tool. `--listar` matters because dashboard tokens are
random and printed only once — losing one means losing access to that client's panel.
`--agregar TOKEN --placas "Mesa 7"` adds supports later. There is no web admin UI yet; editing an
existing `google_review_url` is still a one-off snippet against `app.database.SessionLocal`.

**Any script that prints to a Windows console must reconfigure stdout to UTF-8** (see the top of
`scripts/new_client.py`). The default cp1252 console raises `UnicodeEncodeError` on box-drawing
characters and other non-Latin-1 glyphs, and that traceback lands *after* the DB commit — which
silently creates a client that looks like it failed, and invites the operator to create it twice.

```powershell
pip install -r requirements-dev.txt
pytest -q                       # 176 tests
pytest tests/test_metrics.py -q # solo la métrica
```

Tests run on every push via `.github/workflows/tests.yml`, **on SQLite and Postgres both** —
the two disagree (string lengths, timezone offsets) and that disagreement has already caused
two bugs that only showed up in production. They exist mainly to protect three
things: the conversion metric (which already broke once, silently), local-time bucketing, and
the no-gating rule —
`tests/test_flow.py::TestPoliticaDeGoogle` fails if a star selector reappears before the Google
button. `tests/conftest.py` points `DATABASE_URL` at a temp SQLite file *before* importing any
`app` module, because `app.config` and `app.database` build settings and the engine at import
time; without that the suite would write to the real project database.

No linter or build step.

**Schema changes go through Alembic.** `init_db()` runs `create_all` **only on SQLite** (fast path
for tests and a fresh dev DB); on any other engine it just logs a reminder, because creating tables
without Alembic's version row makes the next `upgrade head` fail on already-existing tables. Any
change to an existing database must be a migration — once a client
has a plaque installed, their tap history is irreplaceable.

```powershell
alembic revision --autogenerate -m "qué cambia"   # revisar SIEMPRE lo generado
alembic upgrade head
alembic downgrade -1
```

Two things autogenerate gets wrong and you must fix by hand: a new `NOT NULL` column needs an
explicit `server_default` or the migration fails on any table that already has rows (this
already happened once — see `cdd115ca0d87`), and SQLite needs `batch_alter_table` for column
changes, which `migrations/env.py` enables via `render_as_batch`. The DB URL is read from
`app.config`, never from `alembic.ini`, so migrations can't target a different database than the
app. `tests/test_migraciones.py` fails if models and migrations drift.

Routes: `/r/{token}` (landing), `/r/{token}/go` (logs + 302 to Google), `/r/{token}/feedback`
(POST), `/r/{token}/qr.png`, `/panel/login` · `/panel/logout`, `/dashboard/` (requires session),
`/informe/{business.dashboard_token}` (HTML report, `?mes=AAAA-MM`, defaults to the last
complete month) and `/informe/{token}/pdf`.

Report routes deliberately sit outside `/dashboard`: that path is a WSGI mount and swallows
every route beneath it.

## Architecture

One FastAPI app ([app/main.py](app/main.py)) with a Dash sub-app mounted into it.

**Data model** ([app/models.py](app/models.py)) — the shape carries most of the design:
`Business` (tenant) → `Placement` (one physical plaque/card/sticker, each with its own token) →
`Tap` (funnel events) and `Feedback` (private complaints). `Tap.session_id` is what makes a real
funnel possible: without it there's no way to know which `landed` event belongs to which
`went_to_google` event. Outcomes are `landed` / `went_to_google` / `left_private_feedback`.

**Funnel integrity** ([app/routers/redirect.py](app/routers/redirect.py) +
[app/services/tracking.py](app/services/tracking.py)): a session cookie identifies the visitor;
`_log()` refuses to write the same outcome twice for the same session+placement (so reloads and
double-clicks don't inflate anything); `/go` back-fills a `landed` event if none exists so
conversion can't exceed 100%; bot user-agents are flagged on write and filtered out of every
dashboard query.

**Dashboard** ([app/dashboard/dash_app.py](app/dashboard/dash_app.py)): a Flask-based Dash app
mounted at `/dashboard` through `a2wsgi.WSGIMiddleware` (Starlette dropped its built-in WSGI
adapter). It doesn't share FastAPI's request cycle — it reads `SessionLocal` directly and
re-queries on a `dcc.Interval`.

**Auth** ([app/middleware.py](app/middleware.py) + [app/services/auth.py](app/services/auth.py)):
the panel requires a login (email + password, `scrypt` from the stdlib — no new dependency, and
never a fast hash like SHA-256). Because the Dash app is WSGI it cannot read Starlette's
session, so `DashboardAuthMiddleware` resolves the identity and injects it as an internal
`x-business-id` header. **It strips any client-supplied header of that name first** — without
that, anyone could send it by hand and read another tenant's panel; `tests/test_auth.py` covers
exactly that attack. The middleware is pure ASGI (not `BaseHTTPMiddleware`) because it has to
modify the scope before the mount sees it, and `SessionMiddleware` must be added *after* it so
it ends up outermost and `scope["session"]` exists.

The report route deliberately stays a capability URL with no login: it is emailed to the owner
each month, like an invoice link, and requiring a login on every monthly email would add
friction to the exact feature that drives retention. `dashboard_token` survives only for that.

**Landing** ([app/templates/landing.html](app/templates/landing.html)): server-rendered Jinja2 +
a few lines of vanilla JS, no build step, so the whole product deploys as one Python process.

**Monthly report** ([app/services/report.py](app/services/report.py) +
[app/templates/report.html](app/templates/report.html)): renders to HTML first and PDF second.
The template uses print CSS with `@page` rules and draws its charts with plain CSS blocks — no
JS, no images — so the same markup works in a browser, in "print to PDF", and through WeasyPrint.
WeasyPrint is imported *lazily* inside `render_pdf`: its native GTK libraries don't load on
Windows, and a top-level import would take the whole app down on a dev machine. Missing engine
raises `PDFEngineUnavailable`, which the router turns into a 501 with instructions rather than
a 500.

**Config** ([app/config.py](app/config.py)): `pydantic-settings` reading `.env` (see
`.env.example`; a test asserts every settings field is documented there, since an undocumented
one is one nobody will set on the server).

**Alerting** goes through [app/services/notify.py](app/services/notify.py), never through a
channel module directly. A business can have Telegram, email, both or neither
(`Business.telegram_chat_id`, `Business.alert_email`); `notify()` fans out to whatever is
configured and returns whether *any* channel delivered, so one dead channel can't silence the
alert. Email exists because the channel matters as much as the message: a Chilean SMB owner
reads email daily and may not have Telegram at all, and the complaint alert is the main reason a
client keeps paying. `smtplib` is blocking, so `send_email` hands it to `asyncio.to_thread` —
otherwise an SMTP handshake would freeze the event loop while another customer taps a plaque.

Alerts are dispatched as a `BackgroundTask` so the customer isn't made to wait on Telegram or
SMTP while standing at a counter. Two tiers exist deliberately:
[telegram.py](app/services/telegram.py)'s `send_alert` catches `Exception` and returns nothing
(nothing it does may break a customer's review), while `send_message`/`send_document`/
`send_email` return a bool, because their caller is the monthly send, which has to tell the
scheduler a delivery failed. Don't collapse the two.

**Deployment**: `render.yaml` is the blueprint (`/health`, `0.0.0.0`, `$PORT`); `psycopg` ships
in `requirements.txt` so switching `DATABASE_URL` to Postgres needs no code change. WeasyPrint
is deliberately *not* in `requirements.txt` — its native GTK deps aren't guaranteed on the host,
and a failing build is worse than a missing PDF attachment. The monthly GitHub Actions workflow
installs them itself, so PDFs get generated there.

## Abuse protection

A placement token is **public by design** — it is glued to a table where anyone can read it. A
script that clears cookies between requests could otherwise inflate a client's visits and sink
the conversion rate they pay for. [app/services/ratelimit.py](app/services/ratelimit.py) caps
requests per IP, reading `x-forwarded-for` because the host terminates TLS in front (without it
every visitor would share the proxy's IP and one bucket). **That header is read right-to-left,
taking the rightmost public IP**: Render appends to whatever the client sent rather than replacing
it, so trusting the first entry let anyone rotate a fake IP per request and slip every limit,
brute-forcing the login included. A returning session (one that already has a `landed` event)
converts even when its IP is capped — otherwise the limit could only ever *lower* a client's
conversion during their busiest hour, since a venue's customers all share one IP.

The public limits deliberately **degrade the metric, never the customer**: over the limit the
landing still renders and `/go` still redirects, only the DB write is skipped. Customers in a
venue share the venue's WiFi — one public IP for everyone — so a 429 there would turn a busy
lunch into a wall of errors. Login is the opposite: no legitimate shared IPs to protect and a
client's password at stake, so it returns a real 429, and a successful login resets the counter
so an honest typo isn't punished.

## Security headers

[app/middleware.py](app/middleware.py) adds hardening headers to every response, plus a strict
CSP on public pages only — Dash generates its own inline scripts and a strict CSP would break the
panel, which is behind a login anyway. `Referrer-Policy` is load-bearing here, not decoration:
without it the browser would send the full landing URL — placement token included — to Google as
the referrer. The landing's JS lives in `static/landing.js` rather than inline so the CSP can ban
inline scripts; putting it back in the template would silently break the private channel.

## Operations

`configure_logging` runs at startup ([app/logging_config.py](app/logging_config.py)); startup
also warns about a missing `SESSION_SECRET` or a non-HTTPS `BASE_URL`, and wires Sentry when
`SENTRY_DSN` is set (empty = off, and a failure to initialise never takes the app down;
`send_default_pii=False` keeps customers' private complaints from reaching a third party). `/health` deliberately
does **not** touch the DB (a database blip shouldn't make the host restart a healthy process);
`/health/ready` does, for checking by hand whether the service is genuinely usable.
`scripts/export_data.py` writes a client's taps and complaints to CSV (utf-8-sig, or Excel on
Windows mangles the accents).
