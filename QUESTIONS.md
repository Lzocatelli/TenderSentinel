# QUESTIONS.md — Full Codebase Audit

Technical review of TenderSentinel. Each question is an independent finding.
Answer inline below each question with your decision/instructions.

---

## 1. Documentation & Identity

### Q1. CLAUDE.md still describes LicitaBot/PNCP (Brazilian system)
The entire CLAUDE.md references "Brazilian government tender", "PNCP API", "Portal Nacional de Contratações Públicas", Portuguese field names, and R$ pricing. The codebase now targets US federal contracts via SAM.gov. Should I rewrite CLAUDE.md to reflect the TenderSentinel/SAM.gov reality?

**Answer:**
Yes.

### Q2. PAYMENTS.md references Pagar.me (Brazilian payment gateway)
The file documents Pagar.me integration with BRL pricing (R$99/R$249/R$499), webhook URLs to `/webhook/pagarme`, and PIX/boleto payment methods. The code actually uses Stripe with USD pricing. Delete this file or rewrite for Stripe?

**Answer:**
Delete if it dont have a clear use

### Q3. Hardcoded Railway fallback URL exposed
`app/alertas.py:11` and `app/relatorio.py:11` both have:
```python
BASE_URL = os.getenv("BASE_URL", "https://web-production-54881.up.railway.app")
```
This reveals infrastructure. Should I change the fallback to `https://tendersentinel.com`?

**Answer:**
Yes
---

## 2. Security

### Q4. No password strength validation on signup
`web/app.py:210` — the `cadastro()` route accepts any password (even empty string). Password length is only validated on change (`minha_conta`, line 435: `len(nova_senha) < 8`). Should I add minimum 8 chars on signup too?
**Answer:**
Yes
### Q5. No email format validation on signup or newsletter
`web/app.py:191` and `web/app.py:749` — only checks `if not email`. Someone can register with `asdf` as their email. Should I add basic email regex validation (or use `email-validator` package)?
**Answer:**
Yes
### Q6. No login rate limiting (brute-force possible)
`web/app.py:232` — the login endpoint has no attempt counter or lockout. An attacker could try unlimited password combinations. Should I add Flask-Limiter or a simple counter with cooldown?
**Answer:**
Yes
### Q7. Newsletter signup has no email confirmation (double opt-in)
`web/app.py:772` — emails are stored immediately without verification. Anyone can subscribe someone else's email, which can be considered spam under CAN-SPAM. Should I add a confirmation email step?
**Answer:**
Yes
### Q8. Session cookie SameSite=Lax instead of Strict
`web/app.py:45` — `SESSION_COOKIE_SAMESITE="Lax"` allows cookies on top-level navigations from external sites. For a financial SaaS handling payment data, should this be `"Strict"`?
**Answer:**
Yes
### Q9. Stripe webhook `subscription.deleted` has no idempotency check
`web/app.py:729-739` — the `checkout.session.completed` handler checks `stripe_last_session_id` for idempotency, but `customer.subscription.deleted` doesn't. If Stripe retries, the UPDATE runs multiple times (harmless but inconsistent). Should I add idempotency?
**Answer:**
Yes
### Q10. No HTTPS redirect middleware
There's no explicit HTTP→HTTPS redirect. Railway's load balancer likely handles this, but should I add `ProxyFix` + redirect for belt-and-suspenders?

**Answer:**
Yes
---

## 3. Portuguese Remnants (i18n)

### Q11. `alertas.py:16` email banner still says "LicitaBot"
```python
Licita<span style="color:#d4af37">Bot</span>
```
`relatorio.py:19` correctly says "TenderSentinel". Should I fix `alertas.py` to match?

**Answer:**
Yes
### Q12. Portuguese flash messages and email content in newsletter
- `web/app.py:654`: `"Pagamento cancelado. Nenhuma cobrança foi feita."`
- `web/app.py:752`: `"E-mail inválido."`
- `web/app.py:763`: `"Este e-mail já está cadastrado na newsletter."`
- `web/app.py:767`: `"Bem-vindo de volta! Você voltou a receber a newsletter."`
- `web/app.py:780-791`: Newsletter welcome email entirely in Portuguese
- `web/app.py:803`: `"Você foi removido da newsletter."`
- `web/app.py:791`: `"Cadastrado! Você receberá a newsletter toda segunda."`

Should I translate all to English?

**Answer:**
Yes
### Q13. Portuguese variable/function names throughout codebase
Functions: `buscar_licitacoes`, `salvar_licitacoes`, `disparar_alertas`, `contar_licitacoes_hoje`, `verificar_csrf`, `formatar_moeda`, `conectar`
DB columns: `objeto`, `orgao`, `criado_em`, `palavras_chave`, `alertas_enviados`, `licitacoes`
Route names: `/assinar`, `/minha-conta`, `/editar-palavras`, `/editar-perfil`, `/buscar-agora`

Should I rename these to English? Note: renaming DB columns requires a migration and updating every query. Renaming routes changes URLs (may break existing bookmarks/links). What's the scope here?

**Answer:**
Yes, if so, you can tell me if i need to change anything on railway DB
### Q14. CSV export headers still in Portuguese
`web/app.py:495`:
```python
writer.writerow(["Órgão", "Objeto", "Valor (R$)", "Data publicação", "Link", "UF"])
```
Also says "R$" instead of USD. Should I fix?

**Answer:**
Yes
### Q15. CSV filename still `licitacoes.csv`
`web/app.py:504`: `filename=licitacoes.csv`. Change to `contracts.csv` or `opportunities.csv`?

**Answer:**
Yes, contracts.csv
### Q16. Flash message for CSV still in Portuguese
`web/app.py:459`:
```python
flash("O download de CSV está disponível a partir do plano Profissional.", "info")
```

**Answer:**
Change to english
### Q17. Manual search email body has Portuguese text
`web/app.py:377`:
```python
{len(novas)} nova(s) licitação(ões) encontradas!
```
And in the email subject (line 382).

**Answer:**
Translate to english
### Q18. Print/log statements throughout are in Portuguese
- `app/scheduler.py:10`: `"Iniciando busca de licitações..."`
- `app/scheduler.py:14`: `"licitações novas salvas."`
- `app/database.py:124`: `"Tabelas criadas com sucesso!"`
- `main.py:14`: `"Buscando licitações no portal..."`
- Many others.

Should I translate or leave as-is (they're internal logs)?

**Answer:**
Translate
---

## 4. Architecture & Performance

### Q19. No database connection pooling
`app/database.py:8` — `conectar()` creates a new psycopg2 connection every call. On Railway (cloud), each connection has ~50-100ms overhead. Every route, every scheduler run opens/closes a connection. Should I add `psycopg2.pool.SimpleConnectionPool` or switch to SQLAlchemy?

**Answer:**
add `psycopg2.pool.SimpleConnectionPool`
### Q20. No database indexes
The schema in `database.py` creates tables with zero indexes (beyond the implicit UNIQUE/PK ones). Critical missing indexes:
- `licitacoes(data_publicacao)` — used in `WHERE data_publicacao = CURRENT_DATE`
- `licitacoes(objeto)` — used in `ILIKE %keyword%` (needs trigram index for LIKE)
- `clientes(email)` — already has UNIQUE, so implicitly indexed ✓
- `alertas_enviados(cliente_id)` — used in every alert dedup check

Should I add these in the migration block?

**Answer:**
Yes
### Q21. ILIKE %keyword% is slow at scale
`web/app.py:284` and `app/alertas.py:120` both use:
```python
" OR ".join(["l.objeto ILIKE %s"] * len(palavras))
```
With `%keyword%` patterns, PostgreSQL can't use B-tree indexes. For 10k+ rows, this gets slow. Options:
- `pg_trgm` extension + GIN index (best for LIKE/ILIKE)
- PostgreSQL Full Text Search (ts_vector)
- Keep as-is until performance is actually a problem

What's the preference?

**Answer:**
`pg_trgm` extension + GIN index
### Q22. Manual migration system with silent `except: pass`
`database.py:94-98`:
```python
for tabela, col, tipo in migrations:
    try:
        cur.execute(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {col} {tipo};")
    except Exception:
        pass
```
If a migration fails (e.g., type conflict), it's silently swallowed. Should I at least log the error, or move to Alembic for proper migrations?

**Answer:**
log the error
### Q23. No logging system — everything uses `print()`
The entire codebase uses `print()` for logging. No log levels, no structured output, no way to filter debug vs error in production. Should I replace with Python's `logging` module?

**Answer:**
replace it
### Q24. Scheduler timezone is America/Sao_Paulo for a US product
`app/scheduler.py:28`:
```python
tz = timezone("America/Sao_Paulo")
```
Daily alerts fire at 9:00 AM São Paulo time, which is 8:00 AM ET / 5:00 AM PT. US federal contractors would expect Eastern Time. Should I change to `America/New_York`?

**Answer:**
Yes
### Q25. `relatorio.py:144` uses naive UTC datetime
```python
sete_dias_atras = datetime.utcnow() - timedelta(days=7)
```
While scheduler uses timezone-aware datetimes. This inconsistency could cause the weekly report to include/exclude records at timezone boundaries. Should I standardize on timezone-aware datetimes?

**Answer:**
yes
### Q26. `web/app.py:163` was hardcoding `total_hoje=0`
The index route had `total_hoje=0` hardcoded instead of calling `contar_licitacoes_hoje()`. I see it's now fixed to `contar_licitacoes_hoje()`. Confirm this is correct?

**Answer:**
yes
---

## 5. Bugs & Logic Issues

### Q27. Stripe error class namespace
`web/app.py:631`:
```python
except stripe.error.InvalidRequestError:
```
Modern versions of the `stripe` Python package use `stripe.InvalidRequestError` (not `stripe.error.InvalidRequestError`). Depending on the installed version, this could silently fail to catch the exception. Should I check/update?

**Answer:**
yes
### Q28. Race condition in manual search thread
`web/app.py:398` — `buscar_agora()` spawns a daemon thread that calls `buscar_licitacoes()` + `salvar_licitacoes()`. If two users click "Search Now" simultaneously, both threads fetch and insert the same opportunities. The `ON CONFLICT DO NOTHING` handles duplicates, but it's wasteful. Is this acceptable or should I add a lock?

**Answer:**
lock
### Q29. `buscar_agora` email body mixes Portuguese/English
`web/app.py:376-383`:
```python
f"{len(novas)} nova(s) licitação(ões) encontradas!"
```
The email subject also uses Portuguese. This is sent to US users. Bug?

**Answer:**
translate
### Q30. `test_full_flow.py` has hardcoded personal email
Line 28: `meu_email = "luizzocatelli2014@gmail.com"`. This should use an env var or test email. Also, the test keywords are in Portuguese (`"desenvolvimento de software"`, `"serviços de TI"`) which won't match SAM.gov titles. Should I update?

**Answer:**
yes
### Q31. `test_full_flow.py` deletes ALL alert records
Line 41: `cur.execute("DELETE FROM alertas_enviados;")` — this deletes alert history for ALL users, not just the test user. Running this in production would wipe dedup records. Should I scope it or add a safety check?

**Answer:**
sure
### Q32. CSV export fallback query is fragile
`web/app.py:478-487` — there's a try/except where if the first query fails (e.g., missing `uf` column), it falls back to a query without `uf`. This hides real errors. Is this still needed given all columns are now migrated?

**Answer:**
I dont think so
### Q33. Dashboard date format uses Brazilian locale
`web/app.py:419`:
```python
renovacao = datetime.fromtimestamp(sub.current_period_end).strftime("%d/%m/%Y")
```
US users expect MM/DD/YYYY or "March 25, 2026". Should I change the format?

**Answer:**
yes
---

## 6. Code Quality

### Q34. Duplicate `_EMAIL_BANNER` constant
`app/alertas.py:13-22` defines a banner with "LicitaBot" branding.
`app/relatorio.py:17-26` defines the same banner with "TenderSentinel" branding.
Should I move this to a shared module (e.g., `app/email_templates.py`) with a single definition?

**Answer:**
yes
### Q35. Duplicate `BASE_URL` definition
Both `app/alertas.py:11` and `app/relatorio.py:11` define:
```python
BASE_URL = os.getenv("BASE_URL", "https://web-production-54881.up.railway.app")
```
Should I move to a shared config/constants module?

**Answer:**
yes
### Q36. `web/static/style.css` appears mostly unused
The landing page, dashboard, and all templates now use Tailwind CDN classes. The old `style.css` likely has leftover rules from the LicitaBot era. Should I audit and clean it up or delete it entirely?

**Answer:**
do what suits best
### Q37. Inline import inside route handler
`web/app.py:304`:
```python
from app.score import calcular_score
```
This import is inside the `dashboard()` function body. It works but is unconventional. Move to top-level imports?

**Answer:**
sure
### Q38. Magic numbers not extracted to constants
- `LIMIT 50` (dashboard, line 296)
- `LIMIT 500` (CSV export, line 476)
- `timedelta(minutes=5)` (cache TTL, line 142)
- `trial_period_days=7` (Stripe, line 604)
- Keyword limits in `app/utils.py` (1, 5, 20)

Should I extract these to named constants?

**Answer:**
yes
### Q39. `web/app.py` is 900 lines — consider splitting?
The file handles auth, dashboard, Stripe, newsletter, blog, CSRF, and more. Should I split into blueprints (e.g., `web/auth.py`, `web/payments.py`, `web/blog.py`)?

**Answer:**
yes
---

## 7. Missing Features & Improvements

### Q40. No required env var validation at startup
If `STRIPE_SECRET_KEY` is missing, the app starts fine but crashes when a user tries to subscribe. Should I add startup validation for critical env vars (`DATABASE_URL`, `SECRET_KEY`, `STRIPE_SECRET_KEY`, `SAM_API_KEY`)?

**Answer:**
yes
### Q41. No monitoring/alerting for failed scheduler jobs
If `buscar_e_alertar()` throws an exception, it's only printed to stdout. `main.py` sends an admin email on failure, but `scheduler.py` doesn't. Should I add error notification to the scheduler?

**Answer:**
yes
### Q42. No rate limiting on any endpoint
No Flask-Limiter or equivalent. Endpoints like `/login`, `/cadastro`, `/newsletter/cadastro`, `/buscar-agora`, `/export-csv` are all unprotected. Priority: login and signup first? Or global rate limiting?

**Answer:**
login and signup first
### Q43. No unit tests
Only `test_full_flow.py` exists (integration test, Portuguese keywords, hardcoded email, destructive DB operations). Should I create proper unit tests for `score.py`, `utils.py`, and key routes?

**Answer:**
yes
### Q44. Sitemap doesn't include a `<lastmod>` for static pages
`web/app.py:882-886` — static URLs have no `lastmod` date. Google prefers having this. Should I add it?

**Answer:**
yes
### Q45. No `robots.txt`
There's no `robots.txt` route. Should I add one that allows all crawlers and points to the sitemap?

**Answer:**
yes
### Q46. Blog `_load_posts` reads all files on every request
Every request to `/blog`, `/blog/<slug>`, `/api/blog/preview`, and even `/` (via JS fetch to `/api/blog/preview`) re-reads and parses all markdown files from disk. Should I add caching (e.g., `functools.lru_cache` with TTL)?

**Answer:**
yes
### Q47. Related articles in blog are just "the other posts" — no tag matching
`web/app.py:866`:
```python
related = [p for p in all_posts if p["slug"] != slug][:3]
```
This just takes the first 3 non-current posts. Should I match by shared tags for better relevance?

**Answer:**
yes
### Q48. No OpenGraph meta tags on the main landing page
`index.html` has `<title>` but no `og:title`, `og:description`, `og:image`. When shared on LinkedIn/Twitter it won't have a rich preview. Should I add them?

**Answer:**
yes
### Q49. The "Notify Me" button on Agency plan does nothing
`index.html` — the Agency card has a disabled button "Notify Me" that doesn't submit anywhere. Should I connect it to the newsletter signup or create a separate waitlist?

**Answer:**
yes
### Q50. `Procfile` worker timezone comment
The Procfile is fine, but the worker runs on São Paulo timezone (see Q24). If I change the timezone, no Procfile change needed — just confirming.

**Answer:**
ok
---

## End

50 questions total. Answer each one inline and I'll implement the changes based on your decisions.
