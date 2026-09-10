import logging
import sys

from google.adk.agents import Agent

try:
    from google.adk.models.lite_llm import LiteLlm
except ImportError:
    from google.adk.models import LiteLlm

from .sales_db import (approve_followup, create_lead, list_leads, create_followup_draft,
    get_followup, create_followup_from_template, init_db, setup_tracing,
    logger as db_logger,
)

logger = logging.getLogger(__name__)


def _configure_console_logging():
    """Send agent and database logs directly to the terminal."""
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    for app_logger in (logger, db_logger):
        app_logger.setLevel(logging.DEBUG)
        app_logger.propagate = False

        # Add this handler only once to each logger.
        if not any(
            handler.get_name() == "sales_crm_console"
            for handler in app_logger.handlers
        ):
            handler = logging.StreamHandler(sys.stderr)
            handler.set_name("sales_crm_console")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(formatter)

            app_logger.addHandler(handler)


# ADK executes these statements when it imports agent.py.
_configure_console_logging()
setup_tracing()
init_db()

logger.info("Sales CRM startup configured")


LOCAL_MODEL = "ollama_chat/qwen2.5:3b"

local_model = LiteLlm(
    model=LOCAL_MODEL,
    temperature=0,
)


def register_sales_lead(name: str, company: str, email: str, phone: str,
    budget: str, interest: str, timeline: str, source: str = "website") -> dict:
    """
    Register a new sales lead.

    Required fields:
    - name
    - company
    - email
    - phone
    - budget
    - interest
    - timeline

    Source is optional and defaults to website.
    """

    return create_lead(
        name=name,
        company=company,
        email=email,
        phone=phone,
        budget=budget,
        interest=interest,
        timeline=timeline,
        source=source,
    )



def list_sales_leads(limit: str = "5") -> dict:
    """
    List sales leads ordered by score.

    limit is optional and defaults to 5.
    """
    try:
        limit_int = int(str(limit).strip())

    except (ValueError, TypeError):
        logger.debug("Invalid lead-list limit; using default=5")
        limit_int = 5

    return list_leads(limit=limit_int)



def create_sales_followup(lead_id: str, message: str) -> dict:
    """
    Create a follow-up draft for an existing lead.

    The follow-up remains pending.
    A human must approve it before it becomes approved.
    """

    return create_followup_draft(
        lead_id=lead_id,
        message=message,
    )


def check_followup_status(followup_id: str) -> dict:
    """
    Check the status of a follow-up.
    """

    return get_followup(followup_id=followup_id)


def approve_sales_followup(followup_id: str) -> dict:
    """
    Approve a pending follow-up.

    This action is intended for human/admin approval.
    """

    return approve_followup(
        followup_id=followup_id
    )


def create_template_followup(lead_id: str, template_type: str) -> dict:
    """
    Create a follow-up draft from a template.

    template_type can be:
    - demo
    - pricing
    - newsletter
    """

    return create_followup_from_template(
        lead_id=lead_id,
        template_type=template_type,
    )



root_agent = Agent(
    name="sales_lead_agent",

    model=local_model,

    description=(
        "An AI assistant for registering, scoring, "
        "listing sales leads and preparing follow-up drafts."
    ),

    instruction="""
You are a Sales CRM assistant.

Your job is to manage leads and follow-ups using the available tools.

LEADS:
- To register a lead, collect: name, company, email, phone, budget, interest, timeline.
- source is optional; default to "website".
- If all required fields are available, call register_sales_lead immediately.
- Do not ask for id, score, status, or created_at.
- If required information is missing, ask only for the missing fields.
- Let the Python tool handle normalization, scoring, and status.

LISTING:
- Use list_sales_leads when the user asks to list, show, or see leads.

FOLLOW-UPS:
- Use create_sales_followup for a custom follow-up message.
- Use create_template_followup for demo, pricing, or newsletter templates.
- New follow-ups are always drafts with "pending" status.
- Use check_followup_status to check a follow-up.
- Use approve_sales_followup only when the user explicitly asks to approve a follow-up.
- Never claim a follow-up is approved unless the tool confirms it.
- Never invent lead IDs or follow-up IDs.

GENERAL:
- Use the tools instead of guessing.
- If a tool returns an error, explain it clearly.
""",

    tools=[
        register_sales_lead,
        list_sales_leads,
        create_sales_followup,
        check_followup_status,
        approve_sales_followup,
        create_template_followup,
    ],
)