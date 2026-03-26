# TenderSentinel — Security Audit Report

**Date:** March 25, 2026
**Scope:** Full application stack (Flask web, worker, database, third-party integrations)
**Method:** Static code analysis + architectural review

---

## 1. Authentication & Session Management

### 1.1 Password Policy Enforcement
**Vulnerability:** No minimum password length on user registration. The signup route accepted any string, including empty passwords. Password validation only existed on the password *change* form (min 8 chars).

**Attack vector:** An attacker could create accounts with trivially weak passwords (e.g., `"1"`, `"a"`), then brute-force other accounts assuming similarly weak passwords across the user base.

**Fix implemented:**
```python
# web/app.py — signup route
if len(password) < 8:
    flash("Password must be at least 8 characters.", "erro")
    return render_template("cadastro.html")
```

**Status:** Fixed. Minimum 8 characters enforced on both signup and password change.

---

### 1.2 Brute-Force Login Protection
**Vulnerability:** The `/login` endpoint had no rate limiting. An attacker could send unlimited POST requests trying password combinations without any throttling or lockout mechanism.

**Attack vector:** Credential stuffing — automated tools like Hydra or Burp Intruder can attempt thousands of login combinations per minute against an unprotected endpoint.

**Fix implemented:**
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute")
def login():
    ...
```

**Endpoints protected:**
| Endpoint | Limit | Reason |
|---|---|---|
| `/login` | 10/min | Prevents credential stuffing |
| `/signup` | 10/min | Prevents mass account creation |
| `/newsletter/signup` | 5/min | Prevents email bombing |

**Status:** Fixed. Flask-Limiter with in-memory storage. Returns HTTP 429 when exceeded.

---

### 1.3 Session Cookie Hardening
**Vulnerability:** Session cookie had `SameSite=Lax`, which allows the cookie to be sent on top-level GET navigations from external sites. For a SaaS handling payment data and user accounts, this is unnecessarily permissive.

**Attack vector:** A malicious site could craft a link like `https://tendersentinel.com/manage-subscription` — if the user clicks it while logged in, the browser sends the session cookie (Lax allows top-level navigations). While our CSRF protection blocks state-changing POSTs, the GET request itself leaks that the user is authenticated and could expose session metadata.

**Fix implemented:**
```python
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
```

**Status:** Fixed. `SameSite=Strict` — cookie only sent for same-origin requests. `HttpOnly` prevents JavaScript access. `Secure` ensures HTTPS-only in production.

---

## 2. Input Validation

### 2.1 Email Format Validation
**Vulnerability:** Signup and newsletter forms only checked `if not email:` — any non-empty string was accepted as a valid email (e.g., `"asdf"`, `"<script>alert(1)</script>"`).

**Attack vector:**
- **Database pollution:** Invalid emails stored, wasting SendGrid quota on undeliverable sends
- **Stored XSS (mitigated):** While emails are HTML-escaped before rendering, malformed input increases attack surface

**Fix implemented:**
```python
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

def _is_valid_email(email):
    return bool(_EMAIL_RE.match(email))
```

Applied to: `/signup`, `/newsletter/signup`

**Status:** Fixed. Regex validates format before any database operation.

---

### 2.2 NAICS Code Validation
**Existing control:** NAICS codes are validated as numeric-only via `isdigit()` check. However, no length validation existed — NAICS codes should be 2-6 digits.

**Risk level:** Low. The `isdigit()` check prevents injection. Length validation is a data quality issue, not a security issue.

**Status:** Acknowledged, not changed. Current validation is sufficient for security purposes.

---

## 3. Cross-Site Request Forgery (CSRF)

### 3.1 CSRF Token Implementation (pre-existing)
**Existing control:** All state-changing POST/PUT/DELETE requests require a CSRF token validated via HMAC comparison:

```python
@app.before_request
def verify_csrf():
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if (request.endpoint or "") in {"api_contador", "health", "webhook_stripe", ...}:
        return
    token_form = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    token_session = session.get("_csrf_token")
    if not token_form or not token_session or not hmac.compare_digest(token_form, token_session):
        abort(400)
```

**Exemptions (justified):**
| Endpoint | Reason |
|---|---|
| `/webhook/stripe` | Verified by Stripe signature (`Stripe-Signature` header) |
| `/api/contador` | Read-only GET endpoint |
| `/health` | Read-only GET endpoint |

**Status:** Already secure. Uses `hmac.compare_digest()` for timing-safe comparison — prevents timing-based token extraction.

---

## 4. Transport Security

### 4.1 HTTPS Redirect
**Vulnerability:** No explicit HTTP→HTTPS redirect. While Railway's load balancer handles this at the infrastructure level, defense-in-depth requires application-level enforcement.

**Attack vector:** If the load balancer configuration changes or the app is deployed to a different provider, HTTP requests would be served in plaintext, exposing session cookies and credentials.

**Fix implemented:**
```python
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

if os.getenv("FLASK_ENV") == "production":
    @app.before_request
    def redirect_to_https():
        if request.scheme == "http":
            return redirect(request.url.replace("http://", "https://", 1), code=301)
```

`ProxyFix` ensures `request.scheme` reads `X-Forwarded-Proto` from the load balancer instead of always seeing `http` from the internal connection.

**Status:** Fixed. Application-level HTTPS enforcement in production.

---

## 5. Payment Security (Stripe)

### 5.1 Webhook Signature Verification (pre-existing)
```python
event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
```
All webhook payloads are verified against Stripe's cryptographic signature. Invalid signatures return HTTP 400.

**Status:** Already secure.

### 5.2 Checkout Session Idempotency (pre-existing)
The `checkout.session.completed` handler checks `stripe_last_session_id` to prevent duplicate plan activations from webhook retries.

**Status:** Already secure.

### 5.3 Subscription Deletion Idempotency
**Vulnerability:** The `customer.subscription.deleted` handler ran `UPDATE clientes SET plano=NULL...` on every webhook delivery without checking if the plan was already NULL. While functionally harmless (same UPDATE), it's inconsistent with the idempotency pattern used for session completion.

**Attack vector:** None directly — but inconsistent idempotency patterns indicate sloppy security hygiene and can mask real issues during debugging.

**Fix implemented:**
```python
elif event["type"] == "customer.subscription.deleted":
    subscription_id = event["data"]["object"]["id"]
    conn = get_connection()
    cur = conn.cursor()

    # Idempotency: skip if already processed
    cur.execute(
        "SELECT id FROM clientes WHERE stripe_subscription_id = %s AND plano IS NOT NULL",
        (subscription_id,)
    )
    if not cur.fetchone():
        cur.close()
        release_connection(conn)
        return "", 200
    ...
```

**Status:** Fixed. Both webhook handlers now follow the same idempotency pattern.

### 5.4 Stripe Error Namespace
**Vulnerability:** Exception handler used `stripe.error.InvalidRequestError` which is the legacy namespace. Modern stripe package versions use `stripe.InvalidRequestError`. If the installed version only supports the new namespace, the exception would go uncaught and bubble up as a 500 error, potentially revealing stack trace information.

**Fix implemented:**
```python
except (stripe.InvalidRequestError, stripe.error.InvalidRequestError):
```

**Status:** Fixed. Catches both namespaces for compatibility.

---

## 6. Email Security

### 6.1 Newsletter Double Opt-In (CAN-SPAM Compliance)
**Vulnerability:** Newsletter signup stored emails immediately without verification. Anyone could subscribe a victim's email address, resulting in unwanted emails sent from TenderSentinel's domain — damaging sender reputation and potentially violating CAN-SPAM Act.

**Attack vector:**
1. Attacker submits `victim@company.com` to `/newsletter/signup`
2. Victim receives unsolicited emails from TenderSentinel
3. Victim marks emails as spam → SendGrid sender reputation degrades
4. TenderSentinel domain gets blacklisted

**Fix implemented:**
- New `confirmed BOOLEAN DEFAULT FALSE` column in `newsletter` table
- Signup sends confirmation email with tokenized link
- `/newsletter/confirm/<token>` activates the subscription
- Only confirmed subscribers receive the weekly digest

```python
# Signup stores with confirmed=FALSE
cur.execute(
    "INSERT INTO newsletter (email, nome, token_descadastro, confirmed) VALUES (%s, %s, %s, FALSE)",
    (email, name, token),
)

# Confirmation endpoint
@app.route("/newsletter/confirm/<token>")
def newsletter_confirm(token):
    cur.execute("UPDATE newsletter SET confirmed = TRUE WHERE token_descadastro = %s AND ativo = TRUE", (token,))
```

**Status:** Fixed. Full double opt-in flow implemented.

### 6.2 HTML Escaping in Emails (pre-existing)
All user-supplied data in email templates is properly escaped via `html.escape()`:
```python
agency_s = html.escape(str(agency or "N/A"))
title_s = html.escape(title_raw[:280] + ...)
first_name = html.escape(name.split()[0])
```

**Status:** Already secure. No XSS risk in email content.

---

## 7. SQL Injection

### 7.1 Parameterized Queries (pre-existing)
All database queries use parameterized statements (`%s` placeholders with psycopg2):
```python
cur.execute("SELECT id FROM clientes WHERE email = %s", (email,))
```

Dynamic query construction for keyword filters builds the SQL structure but passes values as parameters:
```python
filters_sql = " OR ".join(["l.objeto ILIKE %s"] * len(keywords))
cur.execute(f"SELECT ... WHERE ({filters_sql})", params)
```

The `f-string` only controls the *number* of `%s` placeholders, not user input. User input always goes through parameterized values.

**Status:** Already secure. No SQL injection vectors found.

### 7.2 Migration Statement Safety
**Note:** The migration block uses f-strings for table/column names:
```python
cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type};")
```
These values come from a hardcoded list in source code, not user input. No injection risk.

---

## 8. Infrastructure Security

### 8.1 Hardcoded Railway URL Exposure
**Vulnerability:** Two files contained the production Railway hostname as a fallback:
```python
BASE_URL = os.getenv("BASE_URL", "https://web-production-54881.up.railway.app")
```

**Risk:** Reveals internal infrastructure identifiers. If the Railway URL has no custom domain restriction, it could be used to bypass IP-based access controls or WAF rules.

**Fix implemented:** Changed fallback to production domain:
```python
BASE_URL = os.getenv("BASE_URL", "https://tendersentinel.com")
```

Centralized in `app/config.py` — single definition for the entire codebase.

**Status:** Fixed. No infrastructure URLs in source code.

### 8.2 Environment Variable Validation
**Vulnerability:** Missing critical environment variables (e.g., `STRIPE_SECRET_KEY`) only caused errors at runtime when a user triggered the affected feature — no startup warning.

**Fix implemented:**
```python
if os.getenv("FLASK_ENV") == "production":
    _required_env = ["DATABASE_URL", "SECRET_KEY", "STRIPE_SECRET_KEY"]
    _missing_env = [v for v in _required_env if not os.getenv(v)]
    if _missing_env:
        logger.error(f"Missing required environment variables: {', '.join(_missing_env)}")
```

**Status:** Fixed. Logs errors at startup for missing critical variables in production.

---

## 9. Concurrency

### 9.1 Race Condition in Manual Search
**Vulnerability:** The "Search Now" button spawned a new daemon thread each time, calling `fetch_opportunities()` + `save_opportunities()`. If two users clicked simultaneously, both threads would fetch the same data from SAM.gov and attempt concurrent inserts. While `ON CONFLICT DO NOTHING` prevents duplicate rows, it doubles API calls and database load.

**Attack vector:** A malicious user could repeatedly click "Search Now" to amplify API calls to SAM.gov, potentially triggering rate limits (429) and blocking the daily scheduled fetch for all users.

**Fix implemented:**
```python
_search_lock = threading.Lock()

def _run(cid, cemail, ckeywords):
    if not _search_lock.acquire(blocking=False):
        logger.info("Manual search already running, skipping")
        return
    try:
        # ... fetch and process
    finally:
        _search_lock.release()
```

**Status:** Fixed. Only one manual search can run at a time. Concurrent requests are silently skipped.

---

## 10. Logging & Monitoring

### 10.1 Logging Infrastructure
**Vulnerability:** Entire codebase used `print()` for logging. No log levels, no timestamps, no module identification. In production, this makes it impossible to:
- Distinguish errors from info messages
- Filter logs by severity
- Correlate events across modules
- Set up alerting on error spikes

**Fix implemented:** Replaced all `print()` with Python's `logging` module:
```python
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("tendersentinel")
```

Each module has its own logger namespace (e.g., `tendersentinel.scraper`, `tendersentinel.web`).

**Status:** Fixed. Structured logging with timestamps, levels, and module names.

### 10.2 Scheduler Failure Notifications
**Vulnerability:** If the daily scheduled job (`fetch_and_alert()`) failed, the exception was only printed to stdout. No admin notification. The `main.py` production runner had admin email notification, but the APScheduler worker did not.

**Fix implemented:**
```python
def fetch_and_alert():
    try:
        ...
    except Exception as e:
        error_msg = f"Scheduler job failed:\n\n{traceback.format_exc()}"
        logger.error(error_msg)
        admin_email = os.getenv("ADMIN_EMAIL")
        if admin_email:
            send_email(admin_email, "TenderSentinel — Daily job failure", f"<pre>{error_msg}</pre>")
```

**Status:** Fixed. Admin receives email on scheduler failures.

---

## Summary Matrix

| # | Category | Issue | Severity | Status |
|---|---|---|---|---|
| 1.1 | Auth | No password validation on signup | High | **Fixed** |
| 1.2 | Auth | No login rate limiting | High | **Fixed** |
| 1.3 | Session | SameSite=Lax | Medium | **Fixed** |
| 2.1 | Input | No email validation | Medium | **Fixed** |
| 3.1 | CSRF | Token protection | — | Already secure |
| 4.1 | Transport | No HTTPS redirect | Medium | **Fixed** |
| 5.1 | Payment | Webhook signature | — | Already secure |
| 5.2 | Payment | Session idempotency | — | Already secure |
| 5.3 | Payment | Deletion idempotency | Low | **Fixed** |
| 5.4 | Payment | Stripe error namespace | Medium | **Fixed** |
| 6.1 | Email | No double opt-in | Medium | **Fixed** |
| 6.2 | Email | HTML escaping | — | Already secure |
| 7.1 | SQL | Parameterized queries | — | Already secure |
| 8.1 | Infra | Hardcoded URL | Low | **Fixed** |
| 8.2 | Infra | Env var validation | Medium | **Fixed** |
| 9.1 | Concurrency | Race condition | Medium | **Fixed** |
| 10.1 | Logging | No structured logging | Medium | **Fixed** |
| 10.2 | Monitoring | No failure alerts | High | **Fixed** |

**13 vulnerabilities fixed. 5 controls verified as already secure. 0 outstanding issues.**
