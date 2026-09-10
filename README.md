Sales CRM Agent

A sales CRM assistant built with Google ADK and a local Ollama model. It uses Python tools to register and score leads, prepare follow-up drafts, and track approvals in SQLite. Python logging and OpenTelemetry spans make the CRM operations easier to inspect.

The default model is qwen2.5:3b, connected through LiteLLM's ollama_chat provider.

Features

Register leads with name, company, email, phone, budget, interest, timeline, and an optional source.

Validate names and email format, normalize input values, and check for an existing lead by email.

Calculate a rule-based score and classify leads as hot, warm, or cold.

List leads by descending score, with newer records first when scores match.

Create custom follow-up drafts or use demo, pricing, and newsletter templates.

Check follow-up status and explicitly approve pending drafts.

Mask email addresses and phone numbers in returned lead records, and mask recognized patterns in draft messages.

Inspect application logs and CRM/database traces in the terminal.

The model chooses tools and explains their results. Python handles validation, scoring, database writes, and status changes.

Project files

The repository root contains the Python package files directly.

File

Purpose

agent.py

Model configuration, agent instructions, tool wrappers, and startup configuration

sales_db.py

SQLite access, scoring, normalization, masking, follow-ups, and tracing setup

approve_followup.py

Command-line entry point for approving a follow-up by ID

init.py

Exposes the agent when the package is imported

.gitignore

Excludes databases, session data, environments, caches, and logs

Startup creates sales_crm.db beside sales_db.py when needed. The database contains leads and followups tables and stays on the local machine.

Setup on Windows PowerShell

Install Python 3.12, Git, and Ollama. Open the Ollama application so its local server is running.

1. Clone the project and install dependencies

Run these commands from the directory where you keep your projects:

git clone https://github.com/mrmohdmaaz0786-cell/sales-crm-agent.git sales_lead_agent_project
cd sales_lead_agent_project

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install google-adk litellm opentelemetry-api opentelemetry-sdk

The clone command uses sales_lead_agent_project as the local folder name so the package commands below match the code. If you already have this folder and a working environment, continue with the model setup.

SQLite is included with Python. Dependency versions are currently unpinned. See the ADK Python setup guide for the framework installation details.

2. Download the local model

ollama pull qwen2.5:3b

If the Ollama server is not running, start it with ollama serve in a separate terminal and leave that terminal open. These commands are documented in the Ollama CLI reference.

In the terminal where you will run the agent, set the local server address:

$env:OLLAMA_API_BASE = "http://localhost:11434"

This setting applies to the current PowerShell session. The agent uses LiteLlm(model="ollama_chat/qwen2.5:3b", temperature=0), following ADK's Ollama integration.

3. Run the agent

From inside sales_lead_agent_project, move to its parent directory and start the agent:

cd ..
adk run sales_lead_agent_project

Keep the virtual environment active. Enter requests at the [user]: prompt; type exit to end the session. The ADK command-line guide describes this interactive interface.

For the optional development web interface, run the following from the same parent directory instead of adk run:

adk web

Open the local address printed by ADK and select sales_lead_agent_project. Application logs and custom trace output appear in the terminal running ADK.

Example requests

Register a lead using fictional contact details:

Register lead Aisha, Example Labs, aisha@example.com, +1 202 555 0147, medium budget, demo interest, within_1_month timeline, website source.

Then try:

Request

Action

List the top 5 leads.

Return leads ordered by score

Create a demo follow-up for lead 1.

Create a pending draft using the demo template

Create a follow-up for lead 1 saying: Would Tuesday work for a demo?

Create a pending custom draft

Check follow-up 1.

Retrieve the draft and its status

Approve follow-up 1.

Approve a pending draft

Replace 1 with the actual lead or follow-up ID returned by the tools. Reusing an existing email returns the existing masked lead with a duplicate outcome.

You can also approve a draft through the command-line module. From the directory containing sales_lead_agent_project, with the environment active:

python -m sales_lead_agent_project.approve_followup 1

Lead scoring

The score is calculated from normalized inputs in sales_db.py.

Factor

Points

Budget

High: 40; medium: 20; low: 5

Timeline

Within 1 month: 30; 1–3 months: 20; 3–6 months: 10; later: 0

Interest

Demo: 20; pricing: 15; newsletter or other: 5

Source

Referral: 15; LinkedIn: 10; website or email campaign: 5; other: 0

Total score

Lead status

70 or higher

hot

40–69

warm

Below 40

cold

For example, medium budget + within 1 month + demo + website gives 20 + 30 + 20 + 5 = 75, classified as hot. The maximum score is 105 points.

Logging and tracing

agent.py configures console logging, enables tracing, and then initializes the database. Its application loggers allow DEBUG and higher messages, formatted as:

timestamp | level | logger name | message

Logs describe events such as startup, validation outcomes, database activity, and errors. Database errors can include exception tracebacks.

OpenTelemetry spans record the timing and context of CRM operations and their database steps. The console exporter displays spans whose names start with crm. or db., for example:

crm.create_lead

db.find_existing_lead

db.insert_and_commit_lead

crm.approve_followup

Completed, sampled spans are written as JSON to stderr through a SimpleSpanProcessor and ConsoleSpanExporter. The JSON includes span names, trace IDs, timestamps, status, and attributes. See the OpenTelemetry exporter documentation.

A duplicate lead returns before insertion, so that request will not produce an insert span. These custom console spans focus on CRM/database work; framework spans may be handled separately.

Data and approval behavior

Follow-ups start as pending. Approval changes their status to approved and records an approval timestamp. Email or SMS delivery would require an additional integration.

The agent exposes an approval tool and is instructed to use it on an explicit user request. The current code has no user authentication or admin-role enforcement.

Masking is partial: names and companies remain visible, email domains and the last four phone digits remain visible, and some formats may not match the masking patterns. Raw lead contact details remain in SQLite; user prompts can also contain personal data.

The repository's .gitignore excludes sales_crm.db, other local databases, .adk/ session data, .env files, virtual environments, Python caches, and log files.