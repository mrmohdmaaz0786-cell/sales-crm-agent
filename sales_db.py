import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
import logging


logger = logging.getLogger(__name__)

#----------------------------------------------------------------------------------------------------------------------

import sys

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

tracer = trace.get_tracer(__name__)

_console_tracing_configured = False


def _format_crm_span(span):
    """Print the custom CRM and database spans."""
    if span.name.startswith(("crm.", "db.")):
        return span.to_json() + "\n"

    return ""


def setup_tracing():
    """Enable console tracing once, reusing an existing SDK provider."""
    global _console_tracing_configured

    if _console_tracing_configured:
        return

    provider = trace.get_tracer_provider()

    # A proxy means no actual tracing provider has been configured yet.
    if isinstance(provider, trace.ProxyTracerProvider):
        trace.set_tracer_provider(TracerProvider())
        provider = trace.get_tracer_provider()

    if not isinstance(provider, TracerProvider):
        raise RuntimeError(
            "Console tracing requires an OpenTelemetry SDK TracerProvider."
        )

    exporter = ConsoleSpanExporter(
        out=sys.stderr,
        formatter=_format_crm_span,
    )

    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _console_tracing_configured = True

#----------------------------------------------------------------------------------------------------------------------

# DATABASE FILE
DB_PATH = Path(__file__).parent / "sales_crm.db"

# BASIC PATTERNS FOR MASKING PII
EMAIL_VALID_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

EMAIL_MASK_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

PHONE_MASK_PATTERN = re.compile(
    r"\b(?:\+?\d{1,3}[-.\s]?)?"
    r"(?:\(?\d{2,4}\)?[-.\s]?)?"
    r"\d{3,4}[-.\s]?\d{4}\b"
)

#----------------------------------------------------------------------------------------------------------------------

FOLLOWUP_TEMPLATES = {
    "demo": (
        "Hi {first_name}, thanks for your interest. "
        "Would you like to schedule a demo this week?"
    ),
    "pricing": (
        "Hi {first_name}, thanks for reaching out. "
        "I can share pricing details. What team size are you evaluating for?"
    ),
    "newsletter": (
        "Hi {first_name}, thanks for subscribing. "
        "We will send you product updates and helpful resources."
    ),
}

#----------------------------------------------------------------------------------------------------------------------

#---------------HELPERS---------------#

def _now():
    """
    Returns current UTC time as text.
    """
    return datetime.now(timezone.utc).isoformat()

#----------------------------------------------------------------------------------------------------------------------


def get_connection() -> sqlite3.Connection:
    """Opens and returns a SQLite connection."""

    logger.debug("Opening SQLite connection")

    try:
        conn = sqlite3.connect(DB_PATH)

    except sqlite3.Error:
        logger.exception("Failed to open SQLite connection")
        raise

    conn.row_factory = sqlite3.Row

    logger.debug("SQLite connection opened")

    return conn


#----------------------------------------------------------------------------------------------------------------------

def mask_email_value(email: str) -> str:
    """
    Masks one email address.

    Example:
    ali@acme.com -> a*i@acme.com
    """
    email = (email or "").strip()

    if "@" not in email:
        return email

    local, domain = email.split("@", 1)

    if len(local) <= 2:
        masked_local = local[0] + "*" if local else "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"

#----------------------------------------------------------------------------------------------------------------------

def mask_phone_value(phone: str) -> str:
    """
    Masks one phone number.

    Example:
    +1 555 123 4567 -> ***-***-4567
    """
    digits = re.sub(r"\D", "", phone or "")

    if len(digits) < 10:
        return phone or ""

    return f"***-***-{digits[-4:]}"

#----------------------------------------------------------------------------------------------------------------------

def _mask_email_match(match):
    return mask_email_value(match.group(0))


def _mask_phone_match(match):
    return mask_phone_value(match.group(0))


# Masks emails and phone numbers inside a whole sentence
def mask_pii_text(text: str) -> str:
    """
    Masks emails and phone numbers inside text.
    """
    if not text:
        return ""

    text, email_matches = EMAIL_MASK_PATTERN.subn(_mask_email_match, text)
    text, phone_matches = PHONE_MASK_PATTERN.subn(_mask_phone_match, text)

    logger.debug("PII masking completed: email_matches=%d, phone_matches=%d",
        email_matches, phone_matches
    )

    return text

#----------------------------------------------------------------------------------------------------------------------
#---------------NORMALIZATION---------------#

def normalize_template_type(template_type: str) -> str:
    """
    Converts template request into standard template name.
    """
    template_type = (template_type or "").strip().lower()

    if template_type in {"demo", "demo_followup", "trial"}:
        return "demo"

    if template_type in {"pricing", "price", "quote"}:
        return "pricing"

    if template_type in {"newsletter", "updates", "subscription"}:
        return "newsletter"

    if template_type:
        logger.debug("Unrecognized template type; defaulting to 'demo'")

    return "demo"


#----------------------------------------------------------------------------------------------------------------------

def normalize_budget(budget: str) -> str:
    """
    Converts budget words into standard values:
    high, medium, low
    """
    budget = (budget or "").strip().lower()

    if budget in {"high", "large", "big", "enterprise", "premium"}:
        return "high"

    if budget in {"medium", "mid", "moderate"}:
        return "medium"

    if budget in {"low", "small", "startup", "basic"}:
        return "low"

    if budget:
        logger.debug("Unrecognized budget; defaulting to 'low'")

    return "low"

#----------------------------------------------------------------------------------------------------------------------

def normalize_timeline(timeline: str) -> str:
    """
    Converts timeline words into standard values.
    """
    timeline = (timeline or "").strip().lower()

    if timeline in {"within_1_month", "1 month", "one month", "urgent", "asap", "immediate"}:
        return "within_1_month"

    if timeline in {"1_3_months", "quarter", "next quarter", "1 to 3 months"}:  
        return "1_3_months"

    if timeline in {"3_6_months", "later this year", "3 to 6 months"}:
        return "3_6_months"

    if timeline:
        logger.debug("Unrecognized timeline; defaulting to 'later'")

    return "later"

#----------------------------------------------------------------------------------------------------------------------

def normalize_interest(interest: str) -> str:
    """
    Converts interest words into standard values.
    """
    interest = (interest or "").strip().lower()

    if interest in {"demo", "trial", "poc"}:
        return "demo"

    if interest in {"pricing", "quote", "cost"}:
        return "pricing"

    if interest in {"newsletter", "updates", "info"}:
        return "newsletter"

    if interest:
        logger.debug("Unrecognized interest; defaulting to 'other'")

    return "other"

#----------------------------------------------------------------------------------------------------------------------

def normalize_source(source: str) -> str:
    """
    Converts lead source words into standard values.
    """
    source = (source or "").strip().lower()

    if source in {"website", "web", "site"}:
        return "website"

    if source in {"linkedin", "linked in"}:
        return "linkedin"

    if source in {"email_campaign", "email", "campaign", "newsletter_campaign"}:
        return "email_campaign"

    if source in {"referral", "ref", "recommended"}:
        return "referral"

    if source:
        logger.debug("Unrecognized source; defaulting to 'other'")

    return "other"

# ----------------------------------------------------------------------------------------------------------------------
#---------------LEAD SCORING---------------#

def calculate_lead_score(budget: str, timeline: str, interest: str, source: str = "website"):
    """
    Calculates lead score and status.

    Returns: score, status
    """
    score = 0

    # Budget points
    if budget == "high":
        score += 40
    elif budget == "medium":
        score += 20
    else:
        score += 5

    # Timeline points
    if timeline == "within_1_month":
        score += 30
    elif timeline == "1_3_months":
        score += 20
    elif timeline == "3_6_months":
        score += 10
    else:
        score += 0

    # Interest points
    if interest == "demo":
        score += 20
    elif interest == "pricing":
        score += 15
    elif interest == "newsletter":
        score += 5
    else:
        score += 5

    # Source points
    if source == "referral":
        score += 15
    elif source == "linkedin":
        score += 10
    elif source == "website":
        score += 5
    elif source == "email_campaign":
        score += 5
    else:
        score += 0

    # Lead status
    if score >= 70:
        status = "hot"
    elif score >= 40:
        status = "warm"
    else:
        status = "cold"

    logger.debug(
        "Lead score calculated: score=%d, status=%s",
        score,
        status,
    )

    return score, status

# ----------------------------------------------------------------------------------------------------------------------
#---------------DATABASE INITIALIZATION---------------#

def init_db():
    """Creates CRM tables if they do not exist."""

    with tracer.start_as_current_span("crm.init_db"):
        logger.info("CRM database initialization started")

        conn = get_connection()

        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    company TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    budget TEXT NOT NULL,
                    interest TEXT NOT NULL,
                    timeline TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'website',
                    score INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS followups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    approved_at TEXT
                )
                """
            )

            conn.commit()

        except sqlite3.Error:
            logger.exception("CRM database initialization failed")
            raise

        finally:
            conn.close()

        logger.info("CRM database initialization completed")


#----------------------------------------------------------------------------------------------------------------------
#---------------SAFE OUTPUT HELPERS---------------#

def _safe_lead(row):
    """
    Converts database lead row into safe masked output.

    The LLM should not see raw email or phone if possible.
    """
    lead = dict(row)

    return {
        "id": lead["id"],
        "name": lead["name"],
        "company": lead["company"],
        "email": mask_email_value(lead["email"]),
        "phone": mask_phone_value(lead["phone"]),
        "budget": lead["budget"],
        "interest": lead["interest"],
        "timeline": lead["timeline"],
        "source": lead.get("source", "website"),
        "score": lead["score"],
        "status": lead["status"],
        "created_at": lead["created_at"],
    }

#----------------------------------------------------------------------------------------------------------------------

def _safe_followup(row):
    """
    Converts followup row into safe output.
    """
    followup = dict(row)

    return {
        "id": followup["id"],
        "lead_id": followup["lead_id"],
        "message": followup["message"],
        "status": followup["status"],
        "created_at": followup["created_at"],
        "approved_at": followup["approved_at"],
    }

#----------------------------------------------------------------------------------------------------------------------
#---------------CRM FUNCTIONS---------------#

def create_lead(name: str, company: str, email: str, phone: str, budget: str,
    interest: str, timeline: str, source: str = "website") -> dict:

    """Creates a new sales lead."""

    with tracer.start_as_current_span("crm.create_lead") as span:

        trace_id = trace.format_trace_id(span.get_span_context().trace_id)

        logger.info("Lead creation started: trace_id=%s", trace_id)

        name = (name or "").strip()
        company = (company or "").strip() or "Unknown"
        email = (email or "").strip().lower()
        phone = (phone or "").strip()

        if not name:
            span.set_attribute("crm.outcome", "missing_name")

            logger.info("Lead creation rejected: reason=missing_name trace_id=%s", trace_id,)

            return {
                "status": "error",
                "code": "missing_name",
                "message": "Lead name is required.",
            }

        if not EMAIL_VALID_PATTERN.match(email):

            span.set_attribute("crm.outcome", "invalid_email")

            logger.info("Lead creation rejected: reason=invalid_email trace_id=%s", trace_id,)

            return {
                "status": "error",
                "code": "invalid_email",
                "message": "Lead email is invalid.",
            }

        budget = normalize_budget(budget)
        interest = normalize_interest(interest)
        timeline = normalize_timeline(timeline)
        source = normalize_source(source)

        score, status = calculate_lead_score(
            budget=budget,
            timeline=timeline,
            interest=interest,
            source=source,
        )

        conn = get_connection()

        lead_id = None
        committed = False

        try:
            with tracer.start_as_current_span("db.find_existing_lead"):
                existing_row = conn.execute(
                    "SELECT * FROM leads WHERE email = ?",
                    (email,)).fetchone()

            if existing_row is not None:
                safe_lead = _safe_lead(existing_row)

                span.set_attribute("crm.outcome", "duplicate_lead")
                span.set_attribute("lead.id", existing_row["id"])

                logger.info("Duplicate lead found: lead_id=%s trace_id=%s",
                    existing_row["id"], trace_id,
                )

                return {
                    "status": "duplicate_lead",
                    "code": "duplicate_email",
                    "message": "A lead with this email already exists.",
                    "lead": safe_lead,
                }

            with tracer.start_as_current_span("db.insert_and_commit_lead"):
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO leads (
                        name, company, email, phone,
                        budget, interest, timeline, source,
                        score, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, company, email, phone, budget, interest, timeline, source, score, status, _now()),
                )

                lead_id = cursor.lastrowid
                span.set_attribute("lead.id", lead_id)

                conn.commit()
                committed = True
                span.set_attribute("crm.insert_committed", True)

            with tracer.start_as_current_span("db.fetch_created_lead"):
                lead_row = conn.execute(
                    "SELECT * FROM leads WHERE id = ?",
                    (lead_id,)).fetchone()

            safe_lead = _safe_lead(lead_row)

            span.set_attribute("crm.outcome", "created")
            span.set_attribute("lead.score", score)
            span.set_attribute("lead.status", status)

            logger.info("Lead created: lead_id=%s score=%d status=%s trace_id=%s",
                lead_id, score, status, trace_id)

            return {
                "status": "created",
                "message": "Lead created and scored.",
                "lead": safe_lead,
            }

        except sqlite3.Error as error:
            span.set_attribute("crm.outcome", "database_error")
            span.set_attribute("crm.insert_committed", committed)
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR))

            logger.exception("Lead creation failed: lead_id=%s committed=%s trace_id=%s",
                lead_id, committed, trace_id)

            return {
                "status": "error",
                "code": "database_error",
                "message": str(error),
            }

        finally:
            conn.close()

# ---------------------------------------------------------------------------------------------------------------------

def list_leads(limit: int = 5) -> dict:
    """Lists leads ordered by score, then by ID."""

    with tracer.start_as_current_span("crm.list_leads") as span:

        trace_id = trace.format_trace_id(span.get_span_context().trace_id)

        span.set_attribute("crm.limit", limit)

        logger.info("Lead listing started: limit=%s trace_id=%s",
            limit, trace_id)

        conn = get_connection()

        try:
            with tracer.start_as_current_span("db.list_leads"):
                rows = conn.execute(
                    """
                    SELECT *
                    FROM leads
                    ORDER BY score DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,)).fetchall()

            leads = [_safe_lead(row) for row in rows]

            span.set_attribute("crm.outcome", "success")
            span.set_attribute("crm.result_count", len(leads))

            logger.info("Lead listing completed: count=%d trace_id=%s",
                len(leads), trace_id,
            )

            return {
                "status": "success",
                "leads": leads,
            }

        except sqlite3.Error as error:
            span.set_attribute("crm.outcome", "database_error")
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR))

            logger.exception("Lead listing failed: code=database_error trace_id=%s", trace_id)

            return {
                "status": "error",
                "code": "database_error",
                "message": str(error),
            }

        finally:
            conn.close()

#----------------------------------------------------------------------------------------------------------------------

def create_followup_draft(lead_id, message: str) -> dict:
    """Creates a pending follow-up draft for a lead."""

    with tracer.start_as_current_span("crm.create_followup_draft") as span:

        trace_id = trace.format_trace_id(span.get_span_context().trace_id)

        logger.info("Follow-up draft creation started: trace_id=%s", trace_id)

        try:
            lead_id_int = int(str(lead_id).strip())

        except (ValueError, TypeError):
            span.set_attribute("crm.outcome", "invalid_lead_id")

            logger.info("Follow-up draft rejected: reason=invalid_lead_id trace_id=%s", trace_id)

            return {
                "status": "error",
                "code": "invalid_lead_id",
                "message": "Lead ID must be a number.",
            }

        span.set_attribute("lead.id", lead_id_int)

        message = mask_pii_text((message or "").strip())

        if not message:
            span.set_attribute("crm.outcome", "missing_message")

            logger.info("Follow-up draft rejected: reason=missing_message "
                "lead_id=%s trace_id=%s",
                lead_id_int, trace_id,
            )

            return {
                "status": "error",
                "code": "missing_message",
                "message": "Follow-up message is required.",
            }

        conn = get_connection()

        followup_id = None
        committed = False

        try:
            with tracer.start_as_current_span("db.find_followup_lead"):
                lead_row = conn.execute(
                    """
                    SELECT *
                    FROM leads
                    WHERE id = ?
                    """,
                    (lead_id_int,)).fetchone()

            if lead_row is None:
                span.set_attribute("crm.outcome", "lead_not_found")

                logger.info(
                    "Follow-up draft rejected: reason=lead_not_found "
                    "lead_id=%s trace_id=%s",
                    lead_id_int, trace_id,
                )

                return {
                    "status": "error",
                    "code": "lead_not_found",
                    "message": "Lead not found.",
                }

            with tracer.start_as_current_span("db.insert_and_commit_followup"):
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO followups (
                        lead_id,
                        message,
                        status,
                        created_at,
                        approved_at
                    )
                    VALUES (?, ?, 'pending', ?, NULL)
                    """,
                    (lead_id_int, message, _now()),
                )

                followup_id = cursor.lastrowid
                span.set_attribute("followup.id", followup_id)

                conn.commit()
                committed = True
                span.set_attribute("crm.insert_committed", True)

            with tracer.start_as_current_span("db.fetch_created_followup"):
                followup_row = conn.execute(
                    """
                    SELECT *
                    FROM followups
                    WHERE id = ?
                    """,
                    (followup_id,)).fetchone()

            safe_followup = _safe_followup(followup_row)

            span.set_attribute("crm.outcome", "draft_created")
            span.set_attribute("followup.status", "pending")

            logger.info(
                "Follow-up draft created: followup_id=%s lead_id=%s "
                "status=pending trace_id=%s",
                followup_id, lead_id_int, trace_id,
            )

            return {
                "status": "pending",
                "message": "Follow-up draft created. It requires human approval.",
                "followup": safe_followup,
            }

        except sqlite3.Error as error:
            span.set_attribute("crm.outcome", "database_error")
            span.set_attribute("crm.insert_committed", committed)
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR))

            logger.exception(
                "Follow-up draft creation failed: lead_id=%s followup_id=%s "
                "committed=%s trace_id=%s",
                lead_id_int, followup_id, committed, trace_id,
            )

            return {
                "status": "error",
                "code": "database_error",
                "message": str(error),
            }

        finally:
            conn.close()

#----------------------------------------------------------------------------------------------------------------------

def get_followup(followup_id) -> dict:
    """
    Gets one follow-up by ID.
    """
    with tracer.start_as_current_span("crm.get_followup") as span:

        trace_id = trace.format_trace_id(span.get_span_context().trace_id)

        logger.info("Follow-up lookup started: trace_id=%s", trace_id,)

        try:
            followup_id_int = int(str(followup_id).strip())

        except (ValueError, TypeError):
            span.set_attribute("crm.outcome", "invalid_followup_id")

            logger.info(
                "Follow-up lookup rejected: "
                "reason=invalid_followup_id trace_id=%s",
                trace_id,
            )

            return {
                "status": "error",
                "code": "invalid_followup_id",
                "message": "Follow-up ID must be a number.",
            }

        span.set_attribute("followup.id", followup_id_int)

        conn = get_connection()

        try:
            with tracer.start_as_current_span("db.get_followup"):
                followup_row = conn.execute(
                    """
                    SELECT *
                    FROM followups
                    WHERE id = ?
                    """,
                    (followup_id_int,)).fetchone()

            if followup_row is None:
                span.set_attribute("crm.outcome", "followup_not_found")

                logger.info(
                    "Follow-up not found: followup_id=%s trace_id=%s",
                    followup_id_int, trace_id,
                )

                return {
                    "status": "error",
                    "code": "followup_not_found",
                    "message": "Follow-up not found.",
                }

            safe_followup = _safe_followup(followup_row)

            span.set_attribute("crm.outcome", "success")

            logger.info(
                "Follow-up retrieved: followup_id=%s trace_id=%s",
                followup_id_int, trace_id,
            )

            return {
                "status": "success",
                "followup": safe_followup,
            }

        except sqlite3.Error as error:
            span.set_attribute("crm.outcome", "database_error")
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR))

            logger.exception(
                "Follow-up lookup failed: followup_id=%s trace_id=%s",
                followup_id_int, trace_id,
            )

            return {
                "status": "error",
                "code": "database_error",
                "message": str(error),
            }

        finally:
            conn.close()

#----------------------------------------------------------------------------------------------------------------------

def approve_followup(followup_id) -> dict:
    """
    Admin-only function to approve a pending follow-up.
    """
    with tracer.start_as_current_span("crm.approve_followup") as span:

        trace_id = trace.format_trace_id(span.get_span_context().trace_id)

        logger.info("Follow-up approval started: trace_id=%s", trace_id,)

        try:
            followup_id_int = int(str(followup_id).strip())

        except (ValueError, TypeError):
            span.set_attribute("crm.outcome", "invalid_followup_id")

            logger.info(
                "Follow-up approval rejected: "
                "reason=invalid_followup_id trace_id=%s",
                trace_id,
            )

            return {
                "status": "error",
                "code": "invalid_followup_id",
                "message": "Follow-up ID must be a number.",
            }

        span.set_attribute("followup.id", followup_id_int)

        conn = get_connection()
        committed = False

        try:
            with tracer.start_as_current_span("db.find_followup_for_approval"):
                followup_row = conn.execute(
                    """
                    SELECT *
                    FROM followups
                    WHERE id = ?
                    """,
                    (followup_id_int,)).fetchone()

            if followup_row is None:
                span.set_attribute("crm.outcome", "followup_not_found")

                logger.info(
                    "Follow-up approval rejected: reason=followup_not_found "
                    "followup_id=%s trace_id=%s",
                    followup_id_int, trace_id,
                )

                return {
                    "status": "error",
                    "code": "followup_not_found",
                    "message": "Follow-up not found.",
                }

            if followup_row["status"] == "approved":
                span.set_attribute("crm.outcome", "already_approved")

                logger.info(
                    "Follow-up approval rejected: reason=already_approved "
                    "followup_id=%s trace_id=%s",
                    followup_id_int, trace_id,
                )

                return {
                    "status": "error",
                    "code": "already_approved",
                    "message": "Follow-up is already approved.",
                }

            if followup_row["status"] != "pending":
                span.set_attribute("crm.outcome", "not_pending")

                logger.info(
                    "Follow-up approval rejected: reason=not_pending "
                    "followup_id=%s trace_id=%s",
                    followup_id_int, trace_id,
                )

                return {
                    "status": "error",
                    "code": "not_pending",
                    "message": "Only pending follow-ups can be approved.",
                }

            with tracer.start_as_current_span("db.approve_and_commit_followup"):
                conn.execute(
                    """
                    UPDATE followups
                    SET status = 'approved',
                        approved_at = ?
                    WHERE id = ?
                    """,
                    (_now(), followup_id_int),
                )

                conn.commit()
                committed = True
                span.set_attribute("crm.update_committed", True)

            with tracer.start_as_current_span("db.fetch_approved_followup"):
                updated_row = conn.execute(
                    """
                    SELECT *
                    FROM followups
                    WHERE id = ?
                    """,
                    (followup_id_int,)).fetchone()

            safe_followup = _safe_followup(updated_row)

            span.set_attribute("crm.outcome", "approved")
            span.set_attribute("followup.status", "approved")

            logger.info(
                "Follow-up approved: followup_id=%s trace_id=%s",
                followup_id_int, trace_id,
            )

            return {
                "status": "approved",
                "message": "Follow-up approved by human admin.",
                "followup": safe_followup,
            }

        except sqlite3.Error as error:
            span.set_attribute("crm.outcome", "database_error")
            span.set_attribute("crm.update_committed", committed)
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR))

            logger.exception(
                "Follow-up approval failed: followup_id=%s "
                "committed=%s trace_id=%s",
                followup_id_int, committed, trace_id,
            )

            return {
                "status": "error",
                "code": "database_error",
                "message": str(error),
            }

        finally:
            conn.close()

#----------------------------------------------------------------------------------------------------------------------

def create_followup_from_template(lead_id, template_type: str) -> dict:
    """
    Creates a pending follow-up draft using a template.
    """
    with tracer.start_as_current_span("crm.create_followup_from_template") as span:

        trace_id = trace.format_trace_id(span.get_span_context().trace_id)

        logger.info("Template follow-up creation started: trace_id=%s", trace_id,)

        try:
            lead_id_int = int(str(lead_id).strip())

        except (ValueError, TypeError):
            span.set_attribute("crm.outcome", "invalid_lead_id")

            logger.info(
                "Template follow-up rejected: "
                "reason=invalid_lead_id trace_id=%s",
                trace_id,
            )

            return {
                "status": "error",
                "code": "invalid_lead_id",
                "message": "Lead ID must be a number.",
            }

        span.set_attribute("lead.id", lead_id_int)

        template_type = normalize_template_type(template_type)
        span.set_attribute("followup.template_type", template_type)

        template = FOLLOWUP_TEMPLATES.get(template_type)

        if template is None:
            span.set_attribute("crm.outcome", "template_not_found")
            span.set_status(Status(StatusCode.ERROR))

            logger.error(
                "Follow-up template missing: template_type=%s "
                "lead_id=%s trace_id=%s",
                template_type, lead_id_int, trace_id,
            )

            return {
                "status": "error",
                "code": "template_not_found",
                "message": "Follow-up template not found.",
            }

        conn = get_connection()

        followup_id = None
        committed = False

        try:
            with tracer.start_as_current_span("db.find_lead_for_template"):
                lead_row = conn.execute(
                    """
                    SELECT *
                    FROM leads
                    WHERE id = ?
                    """,
                    (lead_id_int,)).fetchone()

            if lead_row is None:
                span.set_attribute("crm.outcome", "lead_not_found")

                logger.info(
                    "Template follow-up rejected: reason=lead_not_found "
                    "lead_id=%s trace_id=%s",
                    lead_id_int, trace_id,
                )

                return {
                    "status": "error",
                    "code": "lead_not_found",
                    "message": "Lead not found.",
                }

            lead = dict(lead_row)

            first_name = lead.get("name", "there").strip().split(" ")[0]
            message = template.format(first_name=first_name)
            message = mask_pii_text(message)

            with tracer.start_as_current_span("db.insert_and_commit_template_followup"):
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO followups (
                        lead_id,
                        message,
                        status,
                        created_at,
                        approved_at
                    )
                    VALUES (?, ?, 'pending', ?, NULL)
                    """,
                    (lead_id_int, message, _now()),
                )

                followup_id = cursor.lastrowid
                span.set_attribute("followup.id", followup_id)

                conn.commit()
                committed = True
                span.set_attribute("crm.insert_committed", True)

            with tracer.start_as_current_span("db.fetch_template_followup"):
                followup_row = conn.execute(
                    """
                    SELECT *
                    FROM followups
                    WHERE id = ?
                    """,
                    (followup_id,)).fetchone()

            safe_followup = _safe_followup(followup_row)

            span.set_attribute("crm.outcome", "draft_created")
            span.set_attribute("followup.status", "pending")

            logger.info(
                "Template follow-up created: followup_id=%s lead_id=%s "
                "template_type=%s status=pending trace_id=%s",
                followup_id, lead_id_int, template_type, trace_id,
            )

            return {
                "status": "pending",
                "message": "Template follow-up created. It requires human approval.",
                "template_used": template_type,
                "followup": safe_followup,
            }

        except sqlite3.Error as error:
            span.set_attribute("crm.outcome", "database_error")
            span.set_attribute("crm.insert_committed", committed)
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR))

            logger.exception(
                "Template follow-up creation failed: lead_id=%s "
                "followup_id=%s template_type=%s committed=%s trace_id=%s",
                lead_id_int, followup_id, template_type, committed, trace_id,
            )

            return {
                "status": "error",
                "code": "database_error",
                "message": str(error),
            }

        finally:
            conn.close()