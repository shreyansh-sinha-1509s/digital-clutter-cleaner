# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os
import re
import json
from zoneinfo import ZoneInfo
from typing import AsyncGenerator, Generator, Any
from pydantic import BaseModel, Field

from google.adk.workflow import Workflow, node, FunctionNode, START
from google.adk.agents import LlmAgent, Agent
from google.adk.tools import AgentTool
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.genai import types

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from .config import config

# -----------------------------------------------------------------------------
# 1. Pydantic Models for State & Outputs
# -----------------------------------------------------------------------------

class FileClutterPlan(BaseModel):
    proposed_naming_patterns: list[str] = Field(description="List of proposed naming conventions")
    files_to_move: list[dict[str, str]] = Field(description="List of files to move, keys: src, dest")
    folders_to_create: list[str] = Field(description="Folders that need to be created")

class EmailClutterPlan(BaseModel):
    spam_rules: list[str] = Field(description="Suggested email subjects or senders to filter")
    label_assignments: list[dict[str, str]] = Field(description="Senders to map to specific labels, keys: sender, label")
    archive_rules: list[str] = Field(description="Criteria for auto-archiving email threads")

# -----------------------------------------------------------------------------
# 2. Specialized Sub-Agents
# -----------------------------------------------------------------------------

# Model client configured from universal config
model_client = Gemini(model=config.model, retry_options=types.HttpRetryOptions(attempts=3))

# Dynamic uv resolution for Windows compatibility
uv_path = "C:\\Users\\Lenovo\\AppData\\Roaming\\Python\\Python314\\Scripts\\uv.exe"
if not os.path.exists(uv_path):
    uv_path = "uv"

mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=uv_path,
            args=["run", "python", "-m", "app.mcp_server"]
        )
    )
)

file_cleaner_agent = LlmAgent(
    name="file_cleaner_agent",
    model=model_client,
    instruction="""You are an expert file organization assistant.
Analyze file lists, folders, and directories. Suggest folder structures, file movements, and renaming patterns.
Use the list_directory_clutter and dry_run_file_moves tools to scan directories and validate moves.
Provide structured, clear output according to the schema requested.
Do not recommend deleting files unless the user explicitly requested file removal.""",
    output_schema=FileClutterPlan,
    output_key="file_plan",
    tools=[mcp_toolset],
    description="Analyzes files/directories, creates custom folders, and reorganizes clutter."
)

email_cleaner_agent = LlmAgent(
    name="email_cleaner_agent",
    model=model_client,
    instruction="""You are an expert email inbox organizer assistant.
Analyze email subjects, senders, and descriptions of inbox clutter.
Use the generate_email_filter_rules tool to generate importing rule XMLs.
Propose rule-based filters (labels, folders, auto-archive, spam).
Provide structured, clear output according to the schema requested.""",
    output_schema=EmailClutterPlan,
    output_key="email_plan",
    tools=[mcp_toolset],
    description="Analyzes emails/inbox topics and creates filtering, labeling, and archiving rules."
)

# -----------------------------------------------------------------------------
# 3. Central Orchestrator Agent
# -----------------------------------------------------------------------------

orchestrator = LlmAgent(
    name="orchestrator",
    model=model_client,
    instruction="""You are the central coordinator for the Digital Clutter Cleaner.
Your job is to analyze the user's clutter cleaning request and coordinate a detailed cleanup plan.
You have access to two specialized tools:
1. file_cleaner_agent: to organize local files/directories.
2. email_cleaner_agent: to organize emails and inbox rules.

Based on the user's input, delegate the task to the appropriate agent(s) using their tools.
Once they respond, synthesize a final combined plan detailing:
- The sub-agent outputs.
- Any actions recommended (creating folders, moving files, labeling senders).
- Clearly mention if any permanent deletion or destructive actions are part of the plan.

If the user request is simple, direct, or doesn't match the sub-agents' domains, handle it yourself.""",
    tools=[AgentTool(file_cleaner_agent), AgentTool(email_cleaner_agent)],
    description="Central coordinator agent that delegates clutter tasks to file and email cleaner sub-agents."
)

# -----------------------------------------------------------------------------
# 4. Graph Nodes (Function Nodes)
# -----------------------------------------------------------------------------

def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Validates the input for security policies, PII, and injection."""
    text = ""
    if node_input and node_input.parts:
        text = "".join(part.text for part in node_input.parts if part.text)
    
    # 1. PII scrubbing (e.g. Email addresses, SSNs/phones)
    cleaned_text = text
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    cleaned_text = re.sub(email_pattern, "[EMAIL_SCRUBBED]", cleaned_text)
    
    # 2. Prompt injection detection
    injection_keywords = ["ignore previous instructions", "system prompt", "bypass guardrails"]
    detected = any(kw in text.lower() for kw in injection_keywords)
    
    # 3. Domain-specific rule (restricted directories)
    restricted_dirs = ["c:\\windows", "/etc", "system32", "root"]
    restricted_access = any(d in text.lower() for d in restricted_dirs)
    
    # Audit log
    audit_data = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "session_id": ctx.session.id,
        "original_length": len(text),
        "pii_detected": text != cleaned_text,
        "injection_detected": detected,
        "restricted_access_attempt": restricted_access
    }
    
    if detected or restricted_access:
        severity = "CRITICAL" if detected else "WARNING"
        print(json.dumps({"severity": severity, "audit": audit_data}))
        return Event(
            output="Security event triggered: Request blocked due to safety policies.",
            route="security_alert",
            state={"security_status": "blocked", "security_reason": "Policy violation"}
        )
    
    severity = "INFO"
    print(json.dumps({"severity": severity, "audit": audit_data}))
    return Event(
        output=cleaned_text,
        route="clear",
        state={"cleaned_request": cleaned_text, "security_status": "clear"}
    )


def security_error_node(node_input: str) -> Event:
    """Formats and displays security errors."""
    msg = types.Content(role='model', parts=[types.Part.from_text(text=f"⚠️ {node_input}")])
    return Event(content=msg, output=node_input)


def router_node(ctx: Context, node_input: Any) -> Event:
    """Decides if the orchestrator plan requires human-in-the-loop approval."""
    text = ""
    if isinstance(node_input, str):
        text = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        text = "".join(part.text for part in node_input.parts if part.text)
    elif isinstance(node_input, dict):
        text = json.dumps(node_input)
    else:
        text = str(node_input)
    
    # Detect dangerous/destructive actions requiring human approval
    dangerous_keywords = ["delete", "remove", "wipe", "format", "purge", "discard"]
    needs_review = any(kw in text.lower() for kw in dangerous_keywords)
    
    ctx.state["orchestrator_plan"] = text
    
    if needs_review:
        return Event(
            output=text,
            route="needs_review",
            state={"needs_review": True, "review_reason": "Plan contains sensitive actions (deletion/removal)"}
        )
    else:
        return Event(
            output=text,
            route="auto_approve",
            state={"needs_review": False}
        )


async def human_review(ctx: Context, node_input: str) -> AsyncGenerator[Event, None]:
    """Asks for human approval before finalizing the plan."""
    if not ctx.resume_inputs or "approve_plan" not in ctx.resume_inputs:
        review_prompt = f"✋ **Human Review Required**\n\nPlease review and approve the following plan:\n\n{node_input}\n\nType **yes** to approve, or **no** to reject."
        yield Event(content=types.Content(
            role='model',
            parts=[types.Part.from_text(text=review_prompt)]
        ))
        yield RequestInput(interrupt_id="approve_plan", message="Approve plan? (yes/no)")
        return
    
    user_response = ctx.resume_inputs["approve_plan"].strip().lower()
    if "yes" in user_response or "approve" in user_response:
        approved_msg = "✅ Plan approved by user. Proceeding with execution..."
        yield Event(
            content=types.Content(role='model', parts=[types.Part.from_text(text=approved_msg)]),
            output=f"{approved_msg}\n\nOriginal Plan:\n{node_input}",
            state={"user_approved": True}
        )
    else:
        rejected_msg = "❌ Plan rejected by user. Aborting cleanup."
        yield Event(
            content=types.Content(role='model', parts=[types.Part.from_text(text=rejected_msg)]),
            output=f"{rejected_msg}\n\nOriginal Plan was rejected.",
            state={"user_approved": False}
        )


def final_output(node_input: str) -> Generator[Event, None, None]:
    """Formats the final output for presentation."""
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=node_input)]))
    yield Event(output=node_input)

# -----------------------------------------------------------------------------
# 5. Workflow Definition (Graph construction)
# -----------------------------------------------------------------------------

root_agent = Workflow(
    name="digital_clutter_cleaner",
    edges=[
        ('START', security_checkpoint),
        (security_checkpoint, {'clear': orchestrator, 'security_alert': security_error_node}),
        (orchestrator, router_node),
        (router_node, {'needs_review': human_review, 'auto_approve': final_output}),
        (human_review, final_output),
        (security_error_node, final_output),
    ],
    description="Graph-based digital clutter cleaner coordinating sub-agents and human validation."
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
