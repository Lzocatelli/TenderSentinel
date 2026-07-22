"""
AI-generated opportunity summaries, cached in the `opportunity_summaries` table.

Design notes:
- Summaries are generated lazily (on first view), never in bulk during ingestion —
  most opportunities are never opened, so eager generation would burn API cost
  on content nobody reads.
- Cached indefinitely per opportunity, keyed by a hash of the source fields.
  Opportunity text almost never changes after posting, except on amendments —
  the hash naturally invalidates the cache when that happens.
- Uses a small/fast model on purpose: this is extraction + summarization of a
  few hundred words, not a reasoning-heavy task. Model is configurable via
  AI_SUMMARY_MODEL so it can be swapped without a code change.
"""

import hashlib
import json
import logging

import requests

from app.config import ANTHROPIC_API_KEY, AI_SUMMARY_MODEL, ai_summary_enabled
from app.database import get_connection, release_connection
from app.utils import format_currency

logger = logging.getLogger("tendersentinel.summarizer")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

_SYSTEM_PROMPT = """You summarize US federal contract opportunities for small business owners.
Respond with ONLY a JSON object, no preamble, no markdown fences, matching exactly this shape:
{
  "summary": "2-3 plain-English sentences describing what the government is buying and why it might matter to a small business.",
  "key_requirements": ["short bullet", "short bullet"],
  "documents_needed": ["short bullet", "short bullet"],
  "important_dates": ["short bullet", "short bullet"],
  "risk_flags": ["short bullet noting anything unusual or worth double-checking, or empty list if nothing stands out"]
}
Keep every bullet under 15 words. Base everything strictly on the information given — never invent
requirements, documents, or dates that aren't in the input. If information for a field isn't
available, return an empty list for it."""


class SummarizerDisabled(Exception):
    """Raised when AI summaries are requested but no API key is configured."""


def _fetch_opportunity(opportunity_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, orgao, objeto, valor, naics_code, set_aside, deadline
               FROM licitacoes WHERE id = %s""",
            (opportunity_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "agency": row[1],
            "title": row[2],
            "value": row[3],
            "naics_code": row[4],
            "set_aside": row[5],
            "deadline": row[6],
        }
    finally:
        cur.close()
        release_connection(conn)


def _build_source_text(opp: dict) -> str:
    parts = [
        f"Title: {opp['title'] or 'N/A'}",
        f"Agency: {opp['agency'] or 'N/A'}",
        f"Estimated value: {format_currency(opp['value'])}",
        f"NAICS code: {opp['naics_code'] or 'N/A'}",
        f"Set-aside: {opp['set_aside'] or 'None'}",
        f"Response deadline: {opp['deadline'] or 'N/A'}",
    ]
    return "\n".join(parts)


def _source_hash(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def _get_cached_summary(opportunity_id: int, source_hash: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT summary, key_requirements, documents_needed, important_dates,
                      risk_flags, model_used, generated_at
               FROM opportunity_summaries
               WHERE opportunity_id = %s AND source_hash = %s""",
            (opportunity_id, source_hash),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "summary": row[0],
            "key_requirements": row[1] or [],
            "documents_needed": row[2] or [],
            "important_dates": row[3] or [],
            "risk_flags": row[4] or [],
            "model_used": row[5],
            "generated_at": str(row[6]),
            "cached": True,
        }
    finally:
        cur.close()
        release_connection(conn)


def _call_llm(source_text: str) -> dict:
    resp = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": AI_SUMMARY_MODEL,
            "max_tokens": 500,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": source_text}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    parsed = json.loads(text)

    usage = data.get("usage", {})
    return {
        "summary": parsed.get("summary", ""),
        "key_requirements": parsed.get("key_requirements", []),
        "documents_needed": parsed.get("documents_needed", []),
        "important_dates": parsed.get("important_dates", []),
        "risk_flags": parsed.get("risk_flags", []),
        "model_used": AI_SUMMARY_MODEL,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }


def _save_summary(opportunity_id: int, source_hash: str, result: dict) -> None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO opportunity_summaries
                   (opportunity_id, source_hash, summary, key_requirements,
                    documents_needed, important_dates, risk_flags,
                    model_used, input_tokens, output_tokens)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (opportunity_id) DO UPDATE SET
                   source_hash = EXCLUDED.source_hash,
                   summary = EXCLUDED.summary,
                   key_requirements = EXCLUDED.key_requirements,
                   documents_needed = EXCLUDED.documents_needed,
                   important_dates = EXCLUDED.important_dates,
                   risk_flags = EXCLUDED.risk_flags,
                   model_used = EXCLUDED.model_used,
                   input_tokens = EXCLUDED.input_tokens,
                   output_tokens = EXCLUDED.output_tokens,
                   generated_at = NOW()""",
            (
                opportunity_id, source_hash, result["summary"],
                json.dumps(result["key_requirements"]),
                json.dumps(result["documents_needed"]),
                json.dumps(result["important_dates"]),
                json.dumps(result["risk_flags"]),
                result["model_used"], result["input_tokens"], result["output_tokens"],
            ),
        )
        conn.commit()
    finally:
        cur.close()
        release_connection(conn)


def get_or_generate_summary(opportunity_id: int) -> dict:
    """Returns the cached summary if present and current, otherwise generates,
    stores, and returns a new one. Raises SummarizerDisabled if no API key is set."""
    if not ai_summary_enabled:
        raise SummarizerDisabled("ANTHROPIC_API_KEY is not configured")

    opp = _fetch_opportunity(opportunity_id)
    if not opp:
        raise ValueError(f"Opportunity {opportunity_id} not found")

    source_text = _build_source_text(opp)
    source_hash = _source_hash(source_text)

    cached = _get_cached_summary(opportunity_id, source_hash)
    if cached:
        return cached

    try:
        result = _call_llm(source_text)
    except Exception:
        logger.error(f"Summary generation failed for opportunity {opportunity_id}", exc_info=True)
        raise

    _save_summary(opportunity_id, source_hash, result)
    result["cached"] = False
    result["generated_at"] = None  # DB sets it via NOW(); not needed in the fresh response
    return result
