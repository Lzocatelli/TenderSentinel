# TenderSentinel — Site Overview (as of 2026-07-23)

Snapshot of what's actually live in the codebase today: stack, database, hosting,
security, and feature set. For historical implementation notes see
`TENDERSENTINEL_IMPLEMENTATION.md`; this file reflects current state only.

## What it is

TenderSentinel monitors SAM.gov (US federal contract opportunities) and alerts
small businesses to contracts matching their NAICS codes, certifications, and
keywords, with a scoring/pipeline layer on top for paid plans.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask, gunicorn (2 workers) |
| Templates | Jinja2, server-rendered (no frontend framework) |
| CSS | Tailwind CSS, compiled to a static file (`web/static/css/tailwind.css`) — no CDN, no runtime JIT |
| JS | Vanilla JS, no framework/bundler. Per-page inline `<script>` blocks plus one shared file (`web/static/js/onboarding-tour.js`) |
| Database | PostgreSQL (via `psycopg2`, connection pooled) |
| Scheduler | APScheduler (`BlockingScheduler`), runs as a separate Railway process |
| Auth | Password (werkzeug hash) + optional Google OAuth (Authlib), Flask-Login sessions |
| Payments | Stripe Checkout + webhook |
| Email | Amazon SES (primary) → SendGrid (fallback) → Gmail SMTP (last resort) |
| Rate limiting | Flask-Limiter, in-memory storage, per-route limits (no global default) |
| CSRF | Custom session-token implementation (not Flask-WTF) |

## Architecture / processes

Defined in `Procfile`, two Railway processes off the same codebase:

- **`web`**: `gunicorn web.app:app` — the Flask app (signup/login, dashboard,
  pipeline, billing, blog, API endpoints). Runs DB schema migrations
  (`create_tables()`) automatically on every boot.
- **`worker`**: `python -m app.scheduler` — cron jobs:
  - Daily 9:00 AM ET — fetch new SAM.gov opportunities + dispatch email alerts
  - Monday 9:30 AM ET — weekly opportunity digest email
  - Nightly 2:00 AM ET — recompute contract value statistics from historical awards

## Database (PostgreSQL, 15 tables)

| Table | Purpose |
|---|---|
| `clientes` | User accounts (auth, plan, keywords, NAICS/set-asides, Stripe IDs, Google OAuth link) |
| `licitacoes` | Scraped SAM.gov opportunities |
| `alertas_enviados` | Dedup log — which opportunity was emailed to which user (no cascade delete) |
| `newsletter` | Public newsletter subscribers (double opt-in), independent of `clientes` |
| `company_profiles` | Per-user company metadata (revenue range, etc.) |
| `company_naics` | Per-user NAICS codes (primary/secondary) |
| `company_certifications` | Per-user set-aside certifications (SBA, 8(a), HUBZone, WOSB, SDVOSB) |
| `company_keywords` | Per-user weighted keywords (used by the 5-factor scorer) |
| `company_past_performance` | Per-user past contract history, used in scoring |
| `opportunity_match_scores` | Cached 5-factor match score per user × opportunity |
| `historical_awards` | USASpending.gov award history, feeds value estimation |
| `value_statistics` | Precomputed contract value stats per NAICS |
| `opportunity_decisions` | Go/Consider/Skip pipeline decisions per user |
| `decision_history` | Audit trail of decision changes |
| `opportunity_summaries` | Cached AI-generated opportunity summaries (Claude) |

Most `user_id`/`opportunity_id` foreign keys cascade on delete; `alertas_enviados.cliente_id`
does **not** — deleting a user manually requires clearing that table first.

## Hosting & infrastructure

- **App hosting**: Railway (`web` + `worker` processes, Postgres add-on)
- **Domain**: `tendersentinel.com`, registered/DNS-managed at **Name.com**
  (Railway only hosts the app — it is not the domain registrar or DNS host)
- **Corporate email**: Zoho Mail (free tier), `luiz.zocatelli@tendersentinel.com`,
  MX/SPF/DKIM configured via Name.com DNS
- **Outbound email (product)**: Amazon SES primary, SendGrid domain
  authentication (SPF/DKIM CNAMEs) in progress at time of writing
- **Analytics**: Google Analytics 4 (`G-FFBTS4GBNP`), tag present on every
  server-rendered page
- **Lead gen**: Instantly.ai (cold outreach), connecting to a Zoho mailbox —
  recommended to use a domain separate from `tendersentinel.com` to protect
  the primary domain's sender reputation

## Core features

**Discovery & matching**
- Daily SAM.gov scraper (`app/scraper.py`)
- 5-factor match score (0–10): NAICS, set-aside/certification, weighted
  keywords, company-size fit vs. contract value, past performance —
  free/basic plans use a simplified 2-factor version (NAICS + set-aside)
- Contract value estimation from USASpending.gov historical awards by NAICS
- AI-generated opportunity summaries (Claude API), cached per opportunity —
  Professional/Agency plans only
- Auto-classification into Go / Consider / Skip by score threshold

**Alerts & communication**
- Daily automated email digest (9am ET)
- Manual on-demand search ("Search Now") — paid plans only
- Weekly pipeline report email (Mondays)
- Public newsletter with double opt-in

**Pipeline / workflow**
- Go/Consider/Skip dashboard with stats and 7-day deadline view
- Multi-step company profile (NAICS, certifications, weighted keywords, past
  performance)
- CSV export — Professional/Agency plans

**Account & billing**
- Password login + optional Google OAuth (hidden until `GOOGLE_CLIENT_ID`/`SECRET` are set)
- Stripe subscriptions (monthly/annual), 7-day trial, webhook-driven plan updates
- 3 tiers: Basic $79/mo, Professional $179/mo, Agency (price hidden, "coming soon")

**Onboarding**
- Signup form has clickable keyword-suggestion chips (reduces blank-field drop-off)
- First-dashboard-visit spotlight tour (4 steps: welcome, edit keywords, edit
  profile, where opportunities show up) — dependency-free JS, persisted via
  `localStorage` per account, highlighted elements stay genuinely clickable

**Marketing**
- Landing page, Markdown-based blog, sitemap.xml
- English URLs with 301 redirects from legacy pt-BR paths

## Security posture

- **Passwords**: hashed with werkzeug's `generate_password_hash` (never stored
  or logged in plaintext)
- **CSRF**: custom per-session token (`session["_csrf_token"]`), checked via
  `before_request` on every POST/PUT/DELETE except health check, Stripe
  webhook, and two public read-only API endpoints; compared with
  `hmac.compare_digest` (timing-safe)
- **SQL injection**: all queries use parameterized `%s` placeholders —
  no string-interpolated SQL found in the app
- **Session cookies**: `HttpOnly`, `Secure` in production, `SameSite=Lax`
  (was `Strict` — fixed because it silently broke the Google OAuth callback)
- **Rate limiting**: Flask-Limiter on sensitive routes (signup/login/OAuth:
  10/min, password reset area: 5/min, AI summary API: 30/min) — no global
  default limit is set
- **Stripe webhook**: signature-verified via `stripe.Webhook.construct_event`
  with `STRIPE_WEBHOOK_SECRET`, not just trusted on payload alone
- **OAuth**: Google `state` param CSRF-checked by Authlib; account linking by
  verified Google email prevents duplicate-account creation
- **Secrets**: all via environment variables (Railway), `.env.example`
  documents every required/optional var, nothing hardcoded in source
- **Known gaps** (not yet addressed): no explicit security headers set
  (CSP, `X-Frame-Options`, HSTS) beyond what Railway's edge may add; DMARC
  record is currently `p=none` (monitor-only, not enforcing); SES account may
  still be in AWS sandbox mode (only verified recipients can receive mail
  until "production access" is requested)

## Environment variables

See `.env.example` for the full, current list — grouped as: Core (secret key,
base URL), Database, SAM.gov, Stripe, Email (SES/SendGrid/SMTP, checked in
that priority order), Google OAuth, AI summaries (Anthropic API).

## Testing

`pytest` suite in `tests/` (47 tests at time of writing) covers scoring logic
and the AI summarizer service. No browser/integration test suite — UI changes
in this session were verified manually against a local Postgres with Playwright.

## Known pending items (as of this writing)

- SendGrid domain authentication (SPF/DKIM CNAMEs) not yet verified
- SES may still be in sandbox mode — confirm "production access" was granted
  before relying on it for real customer sends
- Agency plan has no price yet ("Pricing coming soon" + waitlist link)
- P1/P2/P3 onboarding/activation ideas (post-signup next-steps messaging,
  mandatory vs. optional profile wizard, "complete your profile" recovery
  email) discussed but not yet built
