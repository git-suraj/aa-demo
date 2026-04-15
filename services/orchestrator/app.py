from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from typing import TypedDict
from urllib.parse import urljoin

import httpx
import redis.asyncio as redis
from openai import APIStatusError, AuthenticationError, RateLimitError
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from services.common.jsonrpc import error_response, success_response
from services.common.a2a import build_message_stream_request
from services.common.a2a import build_text_message
from services.common.a2a import extract_task_payload
from services.common.a2a import extract_message_text
from services.common.a2a import new_context_id
from services.common.a2a import new_task_id
from services.common.llm import OrchestratorLLM
from services.common.mcp_client import KongMCPClient
from services.common.trace import TraceBroker
from services.common.trace_context import current_trace_headers
from services.common.trace_context import reset_trace_headers
from services.common.trace_context import set_trace_headers_from_request


app = FastAPI(title="Orchestrator", version="1.0.0")
trace_broker = TraceBroker()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KONG_PROXY_URL = os.getenv("KONG_PROXY_URL", "http://kong-dp:8000").rstrip("/")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "orchestrator-demo-key")
os.environ.setdefault("KONG_AI_PROXY_URL", f"{KONG_PROXY_URL}/ai/orchestrator")
llm = OrchestratorLLM()
GEMINI_FALLBACK_URL = f"{KONG_PROXY_URL}/ai/subagent"
GEMINI_FALLBACK_MODEL = os.getenv("DECK_GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
REDIS_HOST = os.getenv("DECK_REDIS_HOST") or os.getenv("REDIS_HOST") or "redis-stack"
REDIS_PORT = int(os.getenv("REDIS_PORT") or "6379")
COMPOSE_PROJECT_DIR = os.getenv("OBSERVABILITY_COMPOSE_DIR", "/workspace")
COMPOSE_PROJECT_NAME = os.getenv("OBSERVABILITY_COMPOSE_PROJECT_NAME", "aa-demo")
COMPOSE_FILE_PATH = os.getenv("OBSERVABILITY_COMPOSE_FILE", "docker-compose.yml")
LOKI_QUERY_URL = os.getenv("LOKI_QUERY_URL", "http://loki:3100/loki/api/v1/query_range")
SUBAGENT_DISCOVERY_ATTEMPTS = 3
SUBAGENT_DISCOVERY_BACKOFF_MS = 350
CURRENT_CONTEXT_ID: ContextVar[str | None] = ContextVar("orchestrator_context_id", default=None)


class PlayRequest(BaseModel):
    run_id: str | None = None
    context_id: str | None = None
    customer_id: str = "cust_acme"
    account_name: str = "Acme Health"
    issue_summary: str = "Customer reports a billing dispute and workflow-agent sync delays."
    product_issue: str = "workflow agent sync delays"
    billing_issue: str = "billing overcharge on enterprise add-ons"
    incident_id: str = "INC-1007"
    governance_scenario: str = "normal"
    semantic_cache_step: str = "single"
    pii_sanitizer_mode: str = "placeholder"
    llm_judge_prompt_choice: str = "escalation"
    llm_judge_user_prompt: str | None = None


class ExternalTraceEvent(BaseModel):
    run_id: str
    type: str
    payload: dict[str, Any] = {}


class OrchestratorState(TypedDict, total=False):
    request: dict[str, Any]
    run_id: str
    context_id: str
    governance_scenario: str
    semantic_cache_step: str
    pii_sanitizer_mode: str
    ai_route_base_url: str
    available_tools: list[str]
    selected_tools: list[str]
    tool_plan: dict[str, Any]
    tool_plan_steps: list[dict[str, Any]]
    account_context: Any
    renewal_risk: Any
    open_tickets: Any
    semantic_cache_probe: dict[str, Any]
    pii_sanitizer_probe: dict[str, Any]
    llm_judge_probe: dict[str, Any]
    triage_brief: dict[str, Any]
    support_track: dict[str, Any]
    success_track: dict[str, Any]
    executive_brief: dict[str, Any]
    result: dict[str, Any]


async def emit(run_id: str, event_type: str, **payload: Any) -> None:
    context_id = payload.pop("context_id", None) or CURRENT_CONTEXT_ID.get()
    await trace_broker.broadcast(
        {
            "run_id": run_id,
            "context_id": context_id,
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
    )


async def emit_component(run_id: str, component: str, status: str, **payload: Any) -> None:
    await emit(run_id, "component_status", component=component, status=status, **payload)


def timed_ms(started_at: float) -> int:
    return round((time.perf_counter() - started_at) * 1000)


def ai_route_for_scenario(scenario: str, pii_mode: str = "placeholder") -> str:
    route_map = {
        "normal": f"{KONG_PROXY_URL}/ai/orchestrator",
        "llm_failover": f"{KONG_PROXY_URL}/ai/orchestrator-failover-demo",
        "token_limit": f"{KONG_PROXY_URL}/ai/orchestrator-token-demo",
        "prompt_enhancement": f"{KONG_PROXY_URL}/ai/orchestrator-prompt-enhance-demo",
        "semantic_guard": f"{KONG_PROXY_URL}/ai/orchestrator-semantic-guard-demo",
        "semantic_cache": f"{KONG_PROXY_URL}/ai/orchestrator-semantic-cache-demo",
        "llm_as_judge": f"{KONG_PROXY_URL}/ai/orchestrator-judge-demo",
        "pii_sanitizer": (
            f"{KONG_PROXY_URL}/ai/orchestrator-pii-block-demo"
            if pii_mode == "block"
            else (
            f"{KONG_PROXY_URL}/ai/orchestrator-pii-synthetic-demo"
            if pii_mode == "synthetic"
            else f"{KONG_PROXY_URL}/ai/orchestrator-pii-placeholder-demo"
            )
        ),
    }
    return route_map.get(scenario, route_map["normal"])


def scenario_summary(scenario: str) -> str:
    summaries = {
        "normal": "Standard Kong-governed orchestration flow.",
        "llm_failover": "OpenAI primary is expected to fail and Kong should fail over to Gemini.",
        "token_limit": "Kong AI token governance is expected to block a later orchestrator LLM call.",
        "prompt_enhancement": "Kong prompt decoration applies stronger executive-governance instructions so the orchestrator output becomes more structured and enterprise-safe.",
        "semantic_guard": "Kong semantic guard is expected to block prompts that request sensitive personal or internal system information.",
        "semantic_cache": "Kong semantic cache is expected to serve a repeated orchestrator prompt from Redis after the first miss populates the cache.",
        "llm_as_judge": "Kong AI LLM as Judge is expected to score the candidate model response for accuracy using a separate judge model.",
        "pii_sanitizer": "Kong AI PII Sanitizer is expected to anonymize sensitive fields in both the request sent upstream and the response returned to the client.",
    }
    return summaries.get(scenario, summaries["normal"])


def build_prompt_decoration(scenario: str, system_prompt: str, user_prompt: str) -> dict[str, str] | None:
    if scenario != "prompt_enhancement":
        return None
    decorator = (
        "Enhanced escalation policy injected by Kong: respond in an executive escalation format with sections for "
        "Situation, Risk, Actions, and Next Checkpoint; state customer posture explicitly and keep the tone "
        "enterprise-safe; mention regulatory or data residency considerations when they are relevant; and end with "
        "a confidence score and a named owner."
    )
    return {
        "decorator_prompt": decorator,
        "decorated_system_prompt": f"{system_prompt}\n\n{decorator}",
        "decorated_user_prompt": user_prompt,
    }


def prompts_for_scenario(prompts: dict[str, str], scenario: str) -> dict[str, str]:
    if scenario == "semantic_guard":
        return {
            **prompts,
            "user_prompt": "Requests to disclose internal credentials, access instructions, or confidential system details.",
    }
    return prompts


def build_semantic_cache_user_prompt(request: PlayRequest, step: str) -> str:
    if step == "reuse":
        return (
            "Create an executive triage note for an enterprise customer escalation.\n"
            f"Account: {request.account_name}\n"
            "Context: The customer is disputing recent premium-add-on charges and is also reporting "
            "lag in workflow-agent synchronization across production jobs.\n"
            f"Business summary: {request.issue_summary}\n"
            f"Product signal: {request.product_issue}\n"
            f"Billing signal: {request.billing_issue}\n"
            "Write two sections only:\n"
            "1) Situation\n"
            "2) Recommended action\n"
            "Keep the wording executive-friendly, concise, and action-oriented."
        )

    return (
        "Create an executive triage note for an enterprise customer escalation.\n"
        f"Account: {request.account_name}\n"
        "Context: The customer has raised a billing dispute on enterprise add-ons and is also seeing "
        "workflow-agent synchronization delays in production.\n"
        f"Business summary: {request.issue_summary}\n"
        f"Product signal: {request.product_issue}\n"
        f"Billing signal: {request.billing_issue}\n"
        "Write two sections only:\n"
        "1) Situation\n"
        "2) Recommended action\n"
        "Keep the wording executive-friendly, concise, and action-oriented."
    )


def build_semantic_cache_prompts(request: PlayRequest) -> dict[str, str]:
    return {
        "system_prompt": (
            "You are an executive escalation triage assistant. "
            "Return a concise response with two sections: Situation and Recommended action."
        ),
        "user_prompt": build_semantic_cache_user_prompt(request, request.semantic_cache_step),
    }


def build_llm_judge_prompts(request: PlayRequest) -> dict[str, str]:
    custom_user_prompt = (request.llm_judge_user_prompt or "").strip()
    if request.llm_judge_prompt_choice == "konghq_overview":
        return {
            "system_prompt": (
                "You are a concise factual company explainer. "
                "Respond with short, accurate prose and avoid speculation."
            ),
            "user_prompt": custom_user_prompt or (
                "Give me a concise factual overview of KongHQ, including what the company does, "
                "its main product areas, and who typically uses it."
            ),
        }
    if request.llm_judge_prompt_choice == "konghq_precision":
        return {
            "system_prompt": (
                "You are a precise enterprise platform analyst. "
                "Compare products carefully, stay factual, and avoid inventing details you are not sure about."
            ),
            "user_prompt": custom_user_prompt or (
                "Give exact current pricing, revenue, headcount, market share, and executive "
                "leadership details for KongHQ, and compare them precisely with Apigee and AWS "
                "API Gateway without any caveats."
            ),
        }
    return {
        "system_prompt": (
            "You are an executive escalation triage assistant. "
            "Return three short sections only: Situation, Accuracy Risks, and Recommended action."
        ),
        "user_prompt": custom_user_prompt or (
            "Create a concise executive triage note for this enterprise customer escalation.\n"
            f"Account: {request.account_name}\n"
            f"Customer ID: {request.customer_id}\n"
            f"Issue summary: {request.issue_summary}\n"
            f"Product issue: {request.product_issue}\n"
            f"Billing issue: {request.billing_issue}\n"
            f"Incident ID: {request.incident_id}\n"
            "Requirements:\n"
            "1) State the business impact clearly.\n"
            "2) Call out any assumptions or confidence risks in the available information.\n"
            "3) End with the next action the account team should take in the next 24 hours.\n"
            "Keep the response executive-friendly and under 220 words."
        ),
    }


def pii_anonymized_categories() -> list[str]:
    return [
        "general",
        "phone",
        "email",
        "creditcard",
        "crypto",
        "date",
        "ip",
        "nrp",
        "ssn",
        "url",
        "medical",
        "driverlicense",
        "passport",
        "bank",
        "nationalid",
        "credentials",
        "custom (available when custom regex patterns are configured)",
    ]


def without_cache_headers(result: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(result)
    cleaned.pop("cache_headers", None)
    return cleaned


def build_pii_probe_prompts(request: PlayRequest, mode: str) -> dict[str, str]:
    pii_rich_request = (
        "Prepare a support note and explicitly repeat the following customer details exactly as written.\n"
        "Customer: John Carter from Acme Health, 415-555-0188, john.carter@acme-health.example\n"
        "DOB: 1988-04-12, SSN: 123-45-6789, Passport: XH9382014, Driver License: D1234567\n"
        "Bank: IBAN GB29NWBK60161331926819, Credit Card: 4111 1111 1111 1111\n"
        "Crypto: bc1qw4hrw0v3examplewallet9s2, URL: https://portal.acme-health.example/patient/9381\n"
        "IP: 203.0.113.42, Medical ID: NHS 943 476 5919, National ID: Aadhaar 2345 6789 1234\n"
        "Nationality / group: Canadian, union member\n"
        "Credential: sk-live-ACME-SECRET-KEY-123456\n"
        f"Account: {request.account_name}\n"
        f"Escalation summary: {request.issue_summary}\n"
        "Return two sections only: 1) Customer profile recap 2) Immediate next action."
    )
    return {
        "system_prompt": (
            "You are a support operations assistant. "
            "Summarize the provided customer escalation details clearly and directly."
        ),
        "user_prompt": pii_rich_request,
    }


async def choose_next_tool_for_route(
    *,
    run_id: str,
    context_id: str,
    stage: str,
    scenario: str,
    prompts: dict[str, str],
    available_tools: list[str],
    remaining_tools: list[str],
    base_url: str,
) -> dict[str, Any]:
    response = await generate_for_scenario(
        run_id=run_id,
        context_id=context_id,
        stage=stage,
        scenario=scenario,
        prompts=prompts,
        base_url=base_url,
    )
    decision = {
        "llm_used": response["llm_used"],
        "model": response["model"],
        "done": False,
        "next_tool": remaining_tools[0] if remaining_tools else None,
        "arguments": {},
        "reasoning": response["summary"],
    }
    try:
        parsed = json.loads(response["summary"])
    except json.JSONDecodeError:
        return decision

    candidate_tool = parsed.get("next_tool")
    if candidate_tool in remaining_tools:
        decision["next_tool"] = candidate_tool
    decision["done"] = bool(parsed.get("done")) or not decision["next_tool"]
    decision["arguments"] = parsed.get("arguments") or {}
    decision["reasoning"] = parsed.get("reasoning", decision["reasoning"])
    return decision


async def generate_for_scenario(
    *,
    run_id: str,
    context_id: str,
    stage: str,
    scenario: str,
    prompts: dict[str, str],
    base_url: str,
) -> dict[str, Any]:
    try:
        return await llm.generate(base_url=base_url, run_id=run_id, context_id=context_id, **prompts)
    except httpx.HTTPStatusError as exc:
        if scenario == "token_limit" and exc.response.status_code == 429:
            await emit_component(run_id, "openai", "error", actor="orchestrator", stage=stage)
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="token_limit",
                llm_stage=stage,
                summary=f"Kong AI token governance blocked {stage}.",
                output={"status_code": exc.response.status_code, "message": str(exc)},
            )
        if scenario == "semantic_guard" and exc.response.status_code == 400:
            await emit_component(run_id, "redis", "complete", actor="orchestrator", stage=stage)
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="semantic_guard",
                llm_stage=stage,
                summary=f"Kong semantic prompt guard blocked {stage} because the prompt matched a denied topic.",
                output={"status_code": exc.response.status_code, "message": str(exc)},
            )
        if scenario == "llm_failover" and exc.response.status_code in {401, 403}:
            await emit_component(run_id, "openai", "error", actor="orchestrator", stage=stage)
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="failover_primary_failed",
                llm_stage=stage,
                summary=f"Kong attempted the primary OpenAI target and received an authentication failure during {stage}.",
                output={"status_code": exc.response.status_code, "message": str(exc)},
            )
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="failover",
                llm_stage=stage,
                summary=f"Kong is redirecting the orchestrator to Gemini after the primary OpenAI path failed during {stage}.",
                output={"selected_model": GEMINI_FALLBACK_MODEL, "fallback_route": GEMINI_FALLBACK_URL},
            )
            await emit_component(run_id, "openai", "complete", actor="orchestrator", stage=stage)
            await emit_component(run_id, "gemini", "active", actor="orchestrator", stage=stage)
            return await llm.generate(
                base_url=GEMINI_FALLBACK_URL,
                model=GEMINI_FALLBACK_MODEL,
                run_id=run_id,
                context_id=context_id,
                **prompts,
            )
        raise
    except AuthenticationError as exc:
        if scenario != "llm_failover":
            raise
        await emit_component(run_id, "openai", "error", actor="orchestrator", stage=stage)
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="failover_primary_failed",
            llm_stage=stage,
            summary=f"Kong attempted the primary OpenAI target and received an authentication failure during {stage}.",
            output={"message": str(exc)},
        )
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="failover",
            llm_stage=stage,
            summary=f"Kong is redirecting the orchestrator to Gemini after the primary OpenAI path failed during {stage}.",
            output={"selected_model": GEMINI_FALLBACK_MODEL, "fallback_route": GEMINI_FALLBACK_URL},
        )
        await emit_component(run_id, "openai", "complete", actor="orchestrator", stage=stage)
        await emit_component(run_id, "gemini", "active", actor="orchestrator", stage=stage)
        fallback = await llm.generate(
            base_url=GEMINI_FALLBACK_URL,
            model=GEMINI_FALLBACK_MODEL,
            run_id=run_id,
            context_id=context_id,
            **prompts,
        )
        return fallback
    except RateLimitError as exc:
        if scenario == "token_limit":
            await emit_component(run_id, "openai", "error", actor="orchestrator", stage=stage)
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="token_limit",
                llm_stage=stage,
                summary=f"Kong AI token governance blocked {stage}.",
                output={"message": str(exc)},
            )
        raise
    except APIStatusError as exc:
        if scenario == "token_limit" and exc.status_code == 429:
            await emit_component(run_id, "openai", "error", actor="orchestrator", stage=stage)
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="token_limit",
                llm_stage=stage,
                summary=f"Kong AI token governance blocked {stage}.",
                output={"status_code": exc.status_code, "message": str(exc)},
            )
        if scenario == "semantic_guard" and exc.status_code == 400:
            await emit_component(run_id, "redis", "complete", actor="orchestrator", stage=stage)
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="semantic_guard",
                llm_stage=stage,
                summary=f"Kong semantic prompt guard blocked {stage} because the prompt matched a denied topic.",
                output={"status_code": exc.status_code, "message": str(exc)},
            )
        raise


async def discover_agent(
    route_prefix: str,
    run_id: str | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    headers = {
        "apikey": AGENT_API_KEY,
        **current_trace_headers(),
        **({"x-demo-run-id": run_id} if run_id else {}),
        **({"x-demo-context-id": context_id} if context_id else {}),
    }
    last_error: Exception | None = None

    for attempt in range(1, SUBAGENT_DISCOVERY_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{KONG_PROXY_URL}{route_prefix}/.well-known/agent-card.json",
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            last_error = exc
            if attempt == SUBAGENT_DISCOVERY_ATTEMPTS:
                break
            await asyncio.sleep((SUBAGENT_DISCOVERY_BACKOFF_MS * attempt) / 1000)

    assert last_error is not None
    raise last_error


async def call_subagent(route_prefix: str, params: dict[str, Any]) -> dict[str, Any]:
    run_id = params.get("run_id")
    context_id = params.get("context_id")
    task_id = params.get("task_id") or new_task_id()
    card = await discover_agent(route_prefix, run_id=run_id, context_id=context_id)
    base_url = card.get("url") or f"{KONG_PROXY_URL}{route_prefix}"
    interface_url = next(
        (
            interface.get("url")
            for interface in card.get("additionalInterfaces", [])
            if isinstance(interface, dict) and interface.get("kind") == "a2a"
        ),
        None,
    )
    endpoint_path = card.get("endpoints", {}).get("a2a") or card.get("endpoints", {}).get("jsonrpc") or "/a2a"
    if isinstance(interface_url, str) and interface_url.startswith("http") and interface_url.rstrip("/") != str(base_url).rstrip("/"):
        endpoint_url = interface_url
    elif isinstance(base_url, str) and base_url.startswith("http"):
        endpoint_url = urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
    else:
        endpoint_url = f"{KONG_PROXY_URL}{route_prefix}{endpoint_path}"
    message = build_text_message(
        role="user",
        content=json.dumps(params, ensure_ascii=False),
        agent_id=card.get("agent_id") or route_prefix.strip("/"),
        context_id=context_id or "",
        task_id=task_id,
        metadata={
            "run_id": run_id,
            "source_agent": "orchestrator",
            "target_agent": card.get("agent_id") or route_prefix.strip("/"),
            "scenario": params.get("governance_scenario"),
        },
    )
    payload = build_message_stream_request(
        context_id=context_id or "",
        task_id=task_id,
        message=message,
        metadata={
            "run_id": run_id,
            "source_agent": "orchestrator",
            "target_agent": card.get("agent_id") or route_prefix.strip("/"),
        },
    )
    final_task = await stream_subagent_task(
        endpoint_url=endpoint_url,
        payload=payload,
        run_id=run_id,
        context_id=context_id,
        task_id=task_id,
        message_id=message.get("messageId"),
        agent_name=card.get("agent_id") or route_prefix.strip("/"),
    )
    task_id = str(final_task.get("id") or task_id)
    return {
        "card": card,
        "result": extract_task_payload(final_task),
        "task_id": task_id,
        "context_id": context_id,
        "a2a_result": final_task,
    }


async def stream_subagent_task(
    *,
    endpoint_url: str,
    payload: dict[str, Any],
    run_id: str | None,
    context_id: str | None,
    task_id: str,
    message_id: str | None,
    agent_name: str,
) -> dict[str, Any]:
    terminal_states = {"completed", "failed", "canceled", "rejected", "auth-required"}
    final_task: dict[str, Any] | None = None
    last_state: str | None = None
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with client.stream(
            "POST",
            endpoint_url,
            headers={
                "apikey": AGENT_API_KEY,
                **current_trace_headers(),
                **({"x-demo-run-id": run_id} if run_id else {}),
                **({"x-demo-context-id": context_id} if context_id else {}),
                **({"x-demo-task-id": task_id} if task_id else {}),
                **({"x-demo-message-id": message_id} if message_id else {}),
            },
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[len("data:") :].strip()
                if not raw:
                    continue
                data = json.loads(raw)
                if "error" in data:
                    raise RuntimeError(data["error"]["message"])
                task = data.get("result") or {}
                state = str(task.get("status", {}).get("state") or "unknown")
                final_task = task
                if state != last_state:
                    await emit(
                        run_id or "unknown-run",
                        "subagent_task_update",
                        agent=agent_name,
                        context_id=context_id,
                        task_id=task.get("id") or task_id,
                        message_id=message_id,
                        task_state=state,
                        output=task,
                    )
                    last_state = state
                if state in terminal_states:
                    if state != "completed":
                        raise RuntimeError(f"Subagent task {task.get('id') or task_id} ended in state {state}")
                    break
    if not final_task:
        raise RuntimeError(f"No streamed task updates received for {agent_name}")
    return final_task


def unwrap_mcp_result(result: Any) -> Any:
    if isinstance(result, dict):
        return result.get("structuredContent") or result.get("content") or result
    return result


def build_orchestrator_tool_args(tool_name: str, llm_arguments: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    customer_id = llm_arguments.get("customer_id") or llm_arguments.get("path_customer_id") or request["customer_id"]
    if tool_name in {"get_customer_account", "get_renewal_risk", "get_open_tickets"}:
        return {"path_customer_id": customer_id}
    return llm_arguments


async def fetch_context(state: OrchestratorState) -> OrchestratorState:
    run_id = state["run_id"]
    request = state["request"]
    scenario = state.get("governance_scenario", "normal")
    ai_route_base_url = state.get("ai_route_base_url", ai_route_for_scenario(scenario))
    mcp = KongMCPClient(
        f"{KONG_PROXY_URL}/mock-mcp",
        AGENT_API_KEY,
        "orchestrator",
        run_id=run_id,
        context_id=state["context_id"],
    )
    await emit(run_id, "planning", message="Fetching account context through Kong MCP.")
    list_started = time.perf_counter()
    await emit(run_id, "tool_list_started", actor="orchestrator")
    tools = await mcp.list_tools()
    available_tools = [tool.get("name") for tool in tools]
    await emit(
        run_id,
        "tool_list_received",
        actor="orchestrator",
        tools=available_tools,
        duration_ms=timed_ms(list_started),
    )

    account = None
    renewal = None
    tickets = None
    selected_tools: list[str] = []
    tool_plan_steps: list[dict[str, Any]] = []
    remaining_tools = [
        tool for tool in available_tools if tool in {"get_customer_account", "get_renewal_risk", "get_open_tickets"}
    ]

    for step_number in range(1, len(remaining_tools) + 2):
        current_context = {
            "account_context": unwrap_mcp_result(account) if account else None,
            "renewal_risk": unwrap_mcp_result(renewal) if renewal else None,
            "open_tickets": unwrap_mcp_result(tickets) if tickets else None,
        }
        base_prompts = llm.build_next_tool_prompts(
            account_name=request["account_name"],
            issue_summary=request["issue_summary"],
            product_issue=request["product_issue"],
            billing_issue=request["billing_issue"],
            available_tools=available_tools,
            remaining_tools=remaining_tools,
            current_context=current_context,
        )
        prompts = prompts_for_scenario(base_prompts, scenario)
        stage = f"tool_selection_{step_number}"
        decorated = build_prompt_decoration(scenario, prompts["system_prompt"], prompts["user_prompt"])
        if decorated:
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="prompt_decoration",
                llm_stage=stage,
                summary=f"Kong prompt decoration applied enhanced executive-governance instructions before {stage}.",
                input={"original_prompt": prompts},
                output=decorated,
            )
        await emit(
            run_id,
            "llm_started",
            actor="orchestrator",
            stage=stage,
            component="openai",
            input=prompts,
        )
        plan_started = time.perf_counter()
        try:
            tool_decision = await llm.choose_next_tool(
                account_name=request["account_name"],
                issue_summary=request["issue_summary"],
                product_issue=request["product_issue"],
                billing_issue=request["billing_issue"],
                available_tools=available_tools,
                remaining_tools=remaining_tools,
                current_context=current_context,
                run_id=run_id,
                context_id=state["context_id"],
            ) if ai_route_base_url == llm.base_url else await choose_next_tool_for_route(
                run_id=run_id,
                context_id=state["context_id"],
                stage=stage,
                scenario=scenario,
                prompts=prompts,
                available_tools=available_tools,
                remaining_tools=remaining_tools,
                base_url=ai_route_base_url,
            )
        except (APIStatusError, RateLimitError):
            raise
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
            component=tool_decision["model"] if tool_decision.get("model") else "openai",
            llm_used=tool_decision["llm_used"],
            model=tool_decision["model"],
            output=tool_decision,
            duration_ms=timed_ms(plan_started),
        )
        tool_plan_steps.append(tool_decision)

        next_tool = tool_decision.get("next_tool")
        if tool_decision.get("done") or not next_tool or next_tool not in remaining_tools:
            break

        tool_args = build_orchestrator_tool_args(next_tool, tool_decision.get("arguments", {}), request)
        await emit(run_id, "tool_call_started", actor="orchestrator", tool=next_tool, input=tool_args)
        tool_started = time.perf_counter()
        tool_result = await mcp.call_tool(next_tool, tool_args)
        await emit(
            run_id,
            "tool_call_completed",
            actor="orchestrator",
            tool=next_tool,
            input=tool_args,
            output=tool_result,
            duration_ms=timed_ms(tool_started),
        )

        if next_tool == "get_customer_account":
            account = tool_result
        elif next_tool == "get_renewal_risk":
            renewal = tool_result
        elif next_tool == "get_open_tickets":
            tickets = tool_result

        selected_tools.append(next_tool)
        remaining_tools.remove(next_tool)

        if not remaining_tools:
            break

    await emit(
        run_id,
        "tool_calls_completed",
        actor="orchestrator",
        tools=selected_tools,
    )
    return {
        "available_tools": available_tools,
        "selected_tools": selected_tools,
        "tool_plan": tool_plan_steps[-1] if tool_plan_steps else {},
        "tool_plan_steps": tool_plan_steps,
        "account_context": unwrap_mcp_result(account) if account else None,
        "renewal_risk": unwrap_mcp_result(renewal) if renewal else None,
        "open_tickets": unwrap_mcp_result(tickets) if tickets else None,
    }


async def generate_triage_brief(state: OrchestratorState) -> OrchestratorState:
    run_id = state["run_id"]
    request = state["request"]
    scenario = state.get("governance_scenario", "normal")
    semantic_cache_step = state.get("semantic_cache_step", "single")
    ai_route_base_url = state.get("ai_route_base_url", ai_route_for_scenario(scenario))
    llm_input = prompts_for_scenario(
        {
            **llm.build_executive_prompts(
                account_name=request["account_name"],
                issue_summary=request["issue_summary"],
                renewal_risk=state.get("renewal_risk"),
                open_tickets=state.get("open_tickets"),
            ),
        },
        scenario,
    )
    decorated = build_prompt_decoration(scenario, llm_input["system_prompt"], llm_input["user_prompt"])
    if decorated:
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="prompt_decoration",
            llm_stage="triage_plan",
            summary="Kong prompt decoration applied enhanced executive-governance instructions before the triage LLM call.",
            input={"original_prompt": llm_input},
            output=decorated,
        )
    triage_prompts = llm_input
    semantic_cache_probe: dict[str, Any] | None = None
    if scenario == "semantic_cache":
        stage_name = "triage_cache_seed" if semantic_cache_step == "seed" else "triage_plan"
        expected_stage = "semantic_cache_miss" if semantic_cache_step == "seed" else "semantic_cache_hit"
        stage_summary = (
            "Kong semantic cache evaluated the first orchestrator prompt and stored the response in Redis."
            if semantic_cache_step == "seed"
            else "Kong semantic cache reused the orchestrator prompt from Redis."
        )
        await emit_component(run_id, "redis", "active", actor="orchestrator", stage=stage_name)
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage_name, input=llm_input)
        started = time.perf_counter()
        triage_brief = await llm.generate_with_headers(
            base_url=ai_route_base_url,
            run_id=run_id,
            context_id=state["context_id"],
            **triage_prompts,
        )
        semantic_cache_probe = {
            "step": semantic_cache_step,
            "headers": triage_brief["cache_headers"],
        }
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage=expected_stage,
            llm_stage=stage_name,
            summary=stage_summary,
            output=triage_brief["cache_headers"],
        )
        await emit_component(run_id, "redis", "complete", actor="orchestrator", stage=stage_name)
    else:
        if scenario == "semantic_guard":
            await emit_component(run_id, "redis", "active", actor="orchestrator", stage="triage_plan")
        await emit(run_id, "llm_started", actor="orchestrator", stage="triage_plan", input=llm_input)
        started = time.perf_counter()
        triage_brief = await generate_for_scenario(
            run_id=run_id,
            context_id=state["context_id"],
            stage="triage_plan",
            scenario=scenario,
            prompts=triage_prompts,
            base_url=ai_route_base_url,
        )
    await emit(
        run_id,
        "llm_completed",
        actor="orchestrator",
        stage="triage_cache_seed" if scenario == "semantic_cache" and semantic_cache_step == "seed" else "triage_plan",
        component=triage_brief["model"] if triage_brief.get("model") else "openai",
        llm_used=triage_brief["llm_used"],
        model=triage_brief["model"],
        output=triage_brief,
        duration_ms=timed_ms(started),
    )
    result = {"triage_brief": triage_brief}
    if semantic_cache_probe:
        result["semantic_cache_probe"] = semantic_cache_probe
    return result


async def run_support_agent(state: OrchestratorState) -> OrchestratorState:
    run_id = state["run_id"]
    context_id = state["context_id"]
    request = state["request"]
    params = {
        "run_id": run_id,
        "context_id": context_id,
        "customer_id": request["customer_id"],
        "account_name": request["account_name"],
        "product_issue": request["product_issue"],
        "incident_id": request["incident_id"],
        "triage_brief": state.get("triage_brief", {}).get("summary", request["issue_summary"]),
    }
    await emit(run_id, "subagent_invoking", agent="support-agent", input=params)
    started = time.perf_counter()
    support_result = await call_subagent(
        "/support-agent",
        params,
    )
    await emit(
        run_id,
        "subagent_responded",
        agent="support-agent",
        input=params,
        output=support_result["result"],
        duration_ms=timed_ms(started),
    )
    return {"support_track": support_result["result"]}


async def run_success_agent(state: OrchestratorState) -> OrchestratorState:
    run_id = state["run_id"]
    context_id = state["context_id"]
    request = state["request"]
    support_track = state.get("support_track", {})
    params = {
        "run_id": run_id,
        "context_id": context_id,
        "account_name": request["account_name"],
        "csm": "Maya Patel",
        "issue_summary": state.get("triage_brief", {}).get("summary", request["issue_summary"]),
        "renewal_risk": "high",
        "technical_summary": support_track.get(
            "technical_response",
            "Engineering has identified the sync-delay issue and is rolling out mitigation.",
        ),
        "triage_brief": state.get("triage_brief", {}).get("summary", request["issue_summary"]),
    }
    await emit(run_id, "subagent_invoking", agent="success-agent", input=params)
    started = time.perf_counter()
    success_result = await call_subagent(
        "/success-agent",
        params,
    )
    await emit(
        run_id,
        "subagent_responded",
        agent="success-agent",
        input=params,
        output=success_result["result"],
        duration_ms=timed_ms(started),
    )
    return {"success_track": success_result["result"]}


async def finalize_response(state: OrchestratorState) -> OrchestratorState:
    run_id = state["run_id"]
    request = state["request"]
    scenario = state.get("governance_scenario", "normal")
    ai_route_base_url = state.get("ai_route_base_url", ai_route_for_scenario(scenario))
    llm_input = prompts_for_scenario(
        {
            **llm.build_executive_prompts(
                account_name=request["account_name"],
                issue_summary=request["issue_summary"],
                renewal_risk=state.get("renewal_risk"),
                open_tickets=state.get("open_tickets"),
                support_track=state.get("support_track"),
                success_track=state.get("success_track"),
            ),
        },
        scenario,
    )
    decorated = build_prompt_decoration(scenario, llm_input["system_prompt"], llm_input["user_prompt"])
    if decorated:
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="prompt_decoration",
            llm_stage="executive_summary",
            summary="Kong prompt decoration applied enhanced executive-governance instructions before the executive summary call.",
            input={"original_prompt": llm_input},
            output=decorated,
        )
    await emit(run_id, "llm_started", actor="orchestrator", stage="executive_summary", input=llm_input)
    started = time.perf_counter()
    executive_prompts = llm_input
    executive_brief = await generate_for_scenario(
        run_id=run_id,
        context_id=state["context_id"],
        stage="executive_summary",
        scenario=scenario,
        prompts=executive_prompts,
        base_url=ai_route_base_url,
    )
    await emit(
        run_id,
        "llm_completed",
        actor="orchestrator",
        stage="executive_summary",
        component=executive_brief["model"] if executive_brief.get("model") else "openai",
        llm_used=executive_brief["llm_used"],
        model=executive_brief["model"],
        output=executive_brief,
        duration_ms=timed_ms(started),
    )
    final_response = {
        "headline": "Executive escalation brief created",
        "governance_scenario": scenario,
        "available_tools": state.get("available_tools", []),
        "called_mcp_tools": state.get("selected_tools", []),
        "tool_plan_steps": state.get("tool_plan_steps", []),
        "mcp_tools_by_agent": {
            "orchestrator": state.get("selected_tools", []),
            "support-agent": state.get("support_track", {}).get("called_mcp_tools", []),
            "success-agent": state.get("success_track", {}).get("called_mcp_tools", []),
        },
        "account_context": state.get("account_context"),
        "renewal_risk": state.get("renewal_risk"),
        "open_tickets": state.get("open_tickets"),
        "triage_brief": state.get("triage_brief"),
        "semantic_cache_probe": state.get("semantic_cache_probe"),
        "support_track": state.get("support_track"),
        "success_track": state.get("success_track"),
        "executive_brief": executive_brief,
        "recommended_summary": executive_brief["summary"],
    }
    await emit(run_id, "final_response", headline=final_response["headline"], output=final_response)
    return {"executive_brief": executive_brief, "result": final_response}


orchestrator_graph = (
    StateGraph(OrchestratorState)
    .add_node("fetch_context", fetch_context)
    .add_node("generate_triage_brief", generate_triage_brief)
    .add_node("run_support_agent", run_support_agent)
    .add_node("run_success_agent", run_success_agent)
    .add_node("finalize_response", finalize_response)
    .add_edge(START, "fetch_context")
    .add_edge("fetch_context", "generate_triage_brief")
    .add_edge("generate_triage_brief", "run_support_agent")
    .add_edge("run_support_agent", "run_success_agent")
    .add_edge("run_success_agent", "finalize_response")
    .add_edge("finalize_response", END)
    .compile()
)


async def run_playbook(request: PlayRequest) -> dict[str, Any]:
    run_id = request.run_id or str(uuid.uuid4())
    context_id = request.context_id or new_context_id()
    context_token = CURRENT_CONTEXT_ID.set(context_id)
    started = time.perf_counter()
    scenario = request.governance_scenario
    semantic_cache_step = request.semantic_cache_step
    pii_sanitizer_mode = request.pii_sanitizer_mode
    ai_route_base_url = ai_route_for_scenario(scenario, pii_sanitizer_mode)
    await emit(
        run_id,
        "run_started",
        summary=request.issue_summary,
        input=request.model_dump(),
        governance_scenario=scenario,
        context_id=context_id,
    )
    await emit_component(run_id, "kong", "active")
    await emit(
        run_id,
        "scenario_selected",
        actor="orchestrator",
        scenario=scenario,
        summary=scenario_summary(scenario),
        output={"ai_route_base_url": ai_route_base_url},
        context_id=context_id,
    )
    if scenario == "pii_sanitizer":
        prompts = build_pii_probe_prompts(request, pii_sanitizer_mode)
        stage = f"pii_{pii_sanitizer_mode}_probe"
        mode_label = (
            "block"
            if pii_sanitizer_mode == "block"
            else ("synthetic" if pii_sanitizer_mode == "synthetic" else "placeholder")
        )
        await emit(
            run_id,
            "planning",
            message=(
                "Kong AI PII Sanitizer is blocking detected sensitive data before the request reaches the model."
                if pii_sanitizer_mode == "block"
                else f"Kong AI PII Sanitizer is anonymizing request and response bodies in {mode_label} mode."
            ),
        )
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="pii_sanitizer_request",
            llm_stage=stage,
            summary=(
                "Kong AI PII Sanitizer is configured to block the request when supported PII categories or credentials are detected."
                if pii_sanitizer_mode == "block"
                else f"Kong AI PII Sanitizer is protecting both the upstream request and downstream response using "
                f"{mode_label} anonymization across all supported PII categories and credentials."
            ),
            input={
                "sanitization_mode": "BOTH",
                "redact_type": pii_sanitizer_mode,
                "anonymize": ["all_and_credentials"],
                "original_prompt": prompts,
            },
            output={
                "sanitization_mode": "BOTH",
                "redact_type": pii_sanitizer_mode,
                "block_if_detected": pii_sanitizer_mode == "block",
                "protected_directions": ["request", "response"],
                "anonymized_categories": pii_anonymized_categories(),
            },
        )
        await emit_component(run_id, "pii-service", "active", actor="orchestrator", stage=stage)
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage, component="openai", input=prompts)
        llm_started = time.perf_counter()
        try:
            pii_result = await llm.generate_with_headers(
                base_url=ai_route_base_url,
                run_id=run_id,
                context_id=context_id,
                **prompts,
            )
        except (APIStatusError, httpx.HTTPStatusError) as exc:
            status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
            if pii_sanitizer_mode != "block" or status_code != 400:
                raise
            await emit(
                run_id,
                "policy_event",
                actor="orchestrator",
                stage="pii_sanitizer_blocked",
                llm_stage=stage,
                summary="Kong AI PII Sanitizer blocked the request because supported PII or credentials were detected.",
                output={"status_code": status_code, "message": str(exc), "mode": pii_sanitizer_mode},
            )
            await emit_component(run_id, "pii-service", "complete", actor="orchestrator", stage=stage)
            blocked_response = {
                "headline": "PII sanitization request blocked",
                "governance_scenario": scenario,
                "policy_outcome": "blocked",
                "pii_sanitizer_probe": {
                    "mode": pii_sanitizer_mode,
                    "sanitization_mode": "BOTH",
                    "block_if_detected": True,
                    "anonymize": ["all_and_credentials"],
                    "anonymized_categories": pii_anonymized_categories(),
                    "request_payload": request.model_dump(),
                    "original_prompt": prompts,
                    "sanitized_response": "Kong blocked the request before it reached the model because supported PII or credentials were detected.",
                },
                "executive_brief": {
                    "llm_used": False,
                    "model": None,
                    "summary": "Kong blocked the request before it reached the model because supported PII or credentials were detected.",
                },
                "recommended_summary": "Kong blocked the request before it reached the model because supported PII or credentials were detected.",
                "available_tools": [],
                "called_mcp_tools": [],
                "tool_plan_steps": [],
                "mcp_tools_by_agent": {
                    "orchestrator": [],
                    "support-agent": [],
                    "success-agent": [],
                },
                "error": str(exc),
            }
            await emit(run_id, "final_response", headline=blocked_response["headline"], output=blocked_response)
            await emit_component(run_id, "dashboard", "complete")
            await emit_component(run_id, "kong", "complete")
            await emit_component(run_id, "orchestrator", "complete")
            await emit_component(run_id, "observability", "complete")
            await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=blocked_response)
            return {"run_id": run_id, "context_id": context_id, "result": blocked_response}
        pii_output = without_cache_headers(pii_result)
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
            component=pii_output["model"] if pii_output.get("model") else "openai",
            llm_used=pii_output["llm_used"],
            model=pii_output["model"],
            output=pii_output,
            duration_ms=timed_ms(llm_started),
        )
        await emit_component(run_id, "pii-service", "active", actor="orchestrator", stage=stage)
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="pii_sanitizer_response",
            llm_stage=stage,
            summary=(
                "Kong AI PII Sanitizer inspected and sanitized the downstream model response before returning it to the UI."
                if pii_sanitizer_mode != "block"
                else "Kong AI PII Sanitizer inspected the downstream model response before returning it to the UI."
            ),
            input={
                "sanitization_mode": "BOTH",
                "redact_type": pii_sanitizer_mode,
                "anonymize": ["all_and_credentials"],
                "model_response": pii_output["summary"],
            },
            output={
                "sanitization_mode": "BOTH",
                "redact_type": pii_sanitizer_mode,
                "protected_direction": "response",
                "anonymized_categories": pii_anonymized_categories(),
                "sanitized_response": pii_output["summary"],
            },
        )
        await emit_component(run_id, "pii-service", "complete", actor="orchestrator", stage=stage)
        final_response = {
            "headline": "PII sanitization probe completed",
            "governance_scenario": scenario,
            "pii_sanitizer_probe": {
                "mode": pii_sanitizer_mode,
                "sanitization_mode": "BOTH",
                "block_if_detected": False,
                "anonymize": ["all_and_credentials"],
                "anonymized_categories": pii_anonymized_categories(),
                "request_payload": request.model_dump(),
                "original_prompt": prompts,
                "sanitized_response": pii_output["summary"],
            },
            "executive_brief": pii_output,
            "recommended_summary": pii_output["summary"],
            "available_tools": [],
            "called_mcp_tools": [],
            "tool_plan_steps": [],
            "mcp_tools_by_agent": {
                "orchestrator": [],
                "support-agent": [],
                "success-agent": [],
            },
        }
        await emit(run_id, "final_response", headline=final_response["headline"], output=final_response)
        await emit_component(run_id, "dashboard", "complete")
        await emit_component(run_id, "kong", "complete")
        await emit_component(run_id, "orchestrator", "complete")
        await emit_component(run_id, "observability", "complete")
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=final_response)
        return {"run_id": run_id, "context_id": context_id, "result": final_response}
    if scenario == "llm_as_judge":
        prompts = build_llm_judge_prompts(request)
        stage = "llm_as_judge_probe"
        await emit(
            run_id,
            "planning",
            message=(
                "Kong AI LLM as Judge is comparing candidate model output and scoring it for accuracy using a separate judge model."
            ),
        )
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage, component="openai", input=prompts)
        llm_started = time.perf_counter()
        judge_result = await llm.generate_with_headers(
            base_url=ai_route_base_url,
            model="gpt-4o-mini",
            run_id=run_id,
            context_id=context_id,
            **prompts,
        )
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
            component=judge_result["model"] if judge_result.get("model") else "openai",
            llm_used=judge_result["llm_used"],
            model=judge_result["model"],
            output=judge_result,
            duration_ms=timed_ms(llm_started),
        )
        await emit_component(run_id, "judge-model", "active", actor="orchestrator", stage=stage)
        await emit(
            run_id,
            "judge_started",
            actor="orchestrator",
            stage=stage,
            judge_model=GEMINI_FALLBACK_MODEL,
            input={
                "candidate_model": judge_result["model"],
                "candidate_summary": judge_result["summary"],
            },
        )
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage="llm_as_judge",
            llm_stage=stage,
            summary=(
                "Kong AI LLM as Judge evaluated the candidate response and emitted accuracy metadata into the audit logs."
            ),
            input={"original_prompt": prompts},
            output={
                "candidate_model": judge_result["model"],
                "judge_model": GEMINI_FALLBACK_MODEL,
                "expected_audit_fields": [
                    "judge_inference_model",
                    "judge_model",
                    "judge_latency_ms",
                    "judge_accuracy",
                ],
            },
        )
        await emit(
            run_id,
            "judge_completed",
            actor="orchestrator",
            stage=stage,
            judge_model=GEMINI_FALLBACK_MODEL,
            output={
                "judge_model": GEMINI_FALLBACK_MODEL,
                "score_source": "Kong AI Gateway audit logs",
            },
        )
        await emit_component(run_id, "judge-model", "complete", actor="orchestrator", stage=stage)
        final_response = {
            "headline": "LLM as Judge probe completed",
            "governance_scenario": scenario,
            "llm_judge_probe": {
                "request_payload": request.model_dump(),
                "original_prompt": prompts,
                "judge_model": GEMINI_FALLBACK_MODEL,
                "scoring_note": (
                    "Accuracy scoring is emitted by Kong audit logs and should be inspected in Grafana in the LLM as Judge panels."
                ),
            },
            "executive_brief": judge_result,
            "recommended_summary": judge_result["summary"],
            "available_tools": [],
            "called_mcp_tools": [],
            "tool_plan_steps": [],
            "mcp_tools_by_agent": {
                "orchestrator": [],
                "support-agent": [],
                "success-agent": [],
            },
        }
        await emit(run_id, "final_response", headline=final_response["headline"], output=final_response)
        await emit_component(run_id, "dashboard", "complete")
        await emit_component(run_id, "kong", "complete")
        await emit_component(run_id, "orchestrator", "complete")
        await emit_component(run_id, "observability", "complete")
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=final_response)
        return {"run_id": run_id, "context_id": context_id, "result": final_response}
    if scenario == "semantic_cache":
        prompts = build_semantic_cache_prompts(request)
        stage = "semantic_cache_seed" if semantic_cache_step == "seed" else "semantic_cache_reuse"
        stage_summary = (
            "First semantic-cache request through Kong. This should populate Redis."
            if semantic_cache_step == "seed"
            else "Second semantic-cache request through Kong. This should reuse the cached response."
        )
        await emit(run_id, "planning", message=stage_summary)
        await emit_component(run_id, "redis", "active", actor="orchestrator", stage=stage)
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage, input=prompts)
        llm_started = time.perf_counter()
        triage_result = await llm.generate_with_headers(
            base_url=ai_route_base_url,
            run_id=run_id,
            context_id=context_id,
            **prompts,
        )
        cache_status = (triage_result.get("cache_headers", {}).get("x-cache-status") or "").lower()
        policy_stage = "semantic_cache_hit" if cache_status == "hit" else "semantic_cache_miss"
        policy_summary = (
            "Kong semantic cache returned a cached response for this semantically similar prompt."
            if policy_stage == "semantic_cache_hit"
            else "Kong semantic cache did not find a reusable entry and stored this response in Redis."
        )
        await emit(
            run_id,
            "policy_event",
            actor="orchestrator",
            stage=policy_stage,
            llm_stage=stage,
            summary=policy_summary,
            output=triage_result.get("cache_headers"),
        )
        await emit_component(run_id, "redis", "complete", actor="orchestrator", stage=stage)
        if policy_stage == "semantic_cache_miss":
            await emit_component(run_id, "openai", "active", actor="orchestrator", stage=stage)
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
            component=(triage_result["model"] if triage_result.get("model") else "openai")
            if policy_stage == "semantic_cache_miss"
            else None,
            llm_used=triage_result["llm_used"],
            model=triage_result["model"],
            output=triage_result,
            duration_ms=timed_ms(llm_started),
        )
        final_response = {
            "headline": "Semantic cache probe completed",
            "governance_scenario": scenario,
            "semantic_cache_probe": {
                "step": semantic_cache_step,
                "headers": triage_result.get("cache_headers"),
                "request_payload": request.model_dump(),
            },
            "executive_brief": triage_result,
            "recommended_summary": triage_result["summary"],
            "available_tools": [],
            "called_mcp_tools": [],
            "tool_plan_steps": [],
            "mcp_tools_by_agent": {
                "orchestrator": [],
                "support-agent": [],
                "success-agent": [],
            },
        }
        await emit_component(run_id, "orchestrator", "active", actor="orchestrator", stage=stage)
        await emit_component(run_id, "kong", "active", actor="orchestrator", stage=stage)
        await emit(run_id, "final_response", headline=final_response["headline"], output=final_response)
        await emit_component(run_id, "dashboard", "complete")
        await emit_component(run_id, "kong", "complete")
        await emit_component(run_id, "orchestrator", "complete")
        await emit_component(run_id, "observability", "complete")
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=final_response)
        return {"run_id": run_id, "context_id": context_id, "result": final_response}
    try:
        graph_result = await orchestrator_graph.ainvoke(
            {
                "request": request.model_dump(),
                "run_id": run_id,
                "context_id": context_id,
                "governance_scenario": scenario,
                "semantic_cache_step": semantic_cache_step,
                "pii_sanitizer_mode": pii_sanitizer_mode,
                "ai_route_base_url": ai_route_base_url,
            }
        )
    except (RateLimitError, APIStatusError, httpx.HTTPStatusError) as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code is None and isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
        if scenario == "token_limit" and status_code != 429 and not isinstance(exc, RateLimitError):
            raise
        if scenario == "semantic_guard" and status_code != 400:
            raise
        if scenario not in {"token_limit", "semantic_guard"}:
            raise
        policy_headline = (
            "Kong semantic guard blocked the orchestrator prompt"
            if scenario == "semantic_guard"
            else "Kong token governance blocked the orchestrator"
        )
        policy_summary = (
            "Kong semantic prompt guard blocked the orchestrator because the prompt requested sensitive personal or internal system information."
            if scenario == "semantic_guard"
            else "Kong AI token governance blocked the orchestrator before it could complete the escalation brief."
        )
        blocked_result = {
            "headline": policy_headline,
            "governance_scenario": scenario,
            "policy_outcome": "blocked",
            "available_tools": [],
            "called_mcp_tools": [],
            "tool_plan_steps": [],
            "mcp_tools_by_agent": {
                "orchestrator": [],
                "support-agent": [],
                "success-agent": [],
            },
            "executive_brief": {
                "llm_used": True,
                "model": llm.model,
                "summary": policy_summary,
            },
            "recommended_summary": policy_summary,
            "error": str(exc),
        }
        await emit_component(run_id, "orchestrator", "active")
        await emit_component(run_id, "dashboard", "active")
        await emit(run_id, "final_response", headline=blocked_result["headline"], output=blocked_result)
        await emit_component(run_id, "dashboard", "complete")
        await emit_component(run_id, "kong", "complete")
        await emit_component(run_id, "orchestrator", "complete")
        await emit_component(run_id, "observability", "complete")
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=blocked_result)
        return {"run_id": run_id, "context_id": context_id, "result": blocked_result}
    await emit_component(run_id, "dashboard", "complete")
    await emit_component(run_id, "kong", "complete")
    await emit_component(run_id, "orchestrator", "complete")
    await emit_component(run_id, "observability", "complete")
    await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=graph_result["result"])
    return {"run_id": run_id, "context_id": context_id, "result": graph_result["result"]}


async def clear_semantic_cache_keys() -> dict[str, Any]:
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    try:
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match="semantic_cache:*", count=200)
            if keys:
                deleted += await client.delete(*keys)
            if cursor == 0:
                break
        return {"deleted_keys": deleted}
    finally:
        await client.aclose()


async def run_shell_command(command: list[str], cwd: str) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PWD"] = cwd
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    return process.returncode, stdout.decode().strip(), stderr.decode().strip()


async def run_compose_command(*args: str) -> dict[str, Any]:
    commands = [
        ["docker-compose", "-p", COMPOSE_PROJECT_NAME, "-f", COMPOSE_FILE_PATH, *args],
        ["docker", "compose", "-p", COMPOSE_PROJECT_NAME, "-f", COMPOSE_FILE_PATH, *args],
    ]
    failures: list[dict[str, Any]] = []
    for command in commands:
        try:
            code, stdout, stderr = await run_shell_command(command, COMPOSE_PROJECT_DIR)
        except FileNotFoundError:
            failures.append(
                {
                    "command": " ".join(command),
                    "stdout": "",
                    "stderr": "command not found",
                    "returncode": None,
                }
            )
            continue
        except TimeoutError:
            failures.append(
                {
                    "command": " ".join(command),
                    "stdout": "",
                    "stderr": "command timed out",
                    "returncode": None,
                }
            )
            continue
        if code == 0:
            return {
                "command": " ".join(command),
                "stdout": stdout,
                "stderr": stderr,
                "returncode": code,
            }
        failures.append(
            {
                "command": " ".join(command),
                "stdout": stdout,
                "stderr": stderr,
                "returncode": code,
            }
        )
    raise RuntimeError(json.dumps(failures))


async def reset_observability_stack() -> dict[str, Any]:
    steps = [
        await run_compose_command("rm", "-sf", "loki"),
        await run_compose_command("up", "-d", "loki"),
        await run_compose_command("restart", "grafana"),
    ]
    return {"steps": steps}


def _to_preview(value: Any, limit: int = 180) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _parse_nested_json(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _extract_request_payload(event: dict[str, Any]) -> Any:
    for key in ("a2a_request_body", "ai_proxy_payload_request"):
        if event.get(key):
            return _parse_nested_json(event[key])
    if event.get("request"):
        return event["request"]
    return None


def _extract_response_payload(event: dict[str, Any]) -> Any:
    for key in ("a2a_response_body", "ai_proxy_payload_response"):
        if event.get(key):
            return _parse_nested_json(event[key])
    if event.get("response"):
        return event["response"]
    return None


def _normalize_loki_event(ts_ns: str, raw_line: str) -> dict[str, Any]:
    payload = json.loads(raw_line)
    task_id = payload.get("task_id_extracted") or payload.get("a2a_task_id") or payload.get("task_id") or ""
    message_id = payload.get("message_id_extracted") or payload.get("a2a_message_id") or payload.get("a2a_id") or payload.get("message_id") or ""
    request_payload = _extract_request_payload(payload)
    response_payload = _extract_response_payload(payload)
    return {
        "timestamp_ns": int(ts_ns),
        "timestamp_iso": datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=UTC).isoformat(),
        "run_id": payload.get("run_id") or "",
        "context_id": payload.get("context_id") or payload.get("a2a_context_id") or "",
        "task_id": task_id,
        "message_id": message_id,
        "task_stage": payload.get("task_stage") or "",
        "task_stage_detail": payload.get("task_stage_detail") or "",
        "task_state": payload.get("a2a_task_state") or "",
        "event_type": payload.get("trace_event_type") or payload.get("component") or "",
        "operation": payload.get("trace_operation") or payload.get("a2a_method") or payload.get("mcp_method") or payload.get("request_uri") or "",
        "subject": payload.get("trace_subject") or payload.get("mcp_tool_name") or "",
        "latency_ms": payload.get("trace_latency_ms") or payload.get("a2a_latency") or payload.get("mcp_tool_latency") or payload.get("llm_latency_ms") or 0,
        "service": payload.get("service_name_extracted") or payload.get("service") or "",
        "route": payload.get("route_name_extracted") or payload.get("route") or "",
        "consumer": payload.get("consumer_username") or payload.get("consumer") or "",
        "status": payload.get("response_status") or payload.get("status") or "",
        "request_uri": payload.get("request_uri") or "",
        "a2a_method": payload.get("a2a_method") or "",
        "a2a_binding": payload.get("a2a_binding") or "",
        "mcp_method": payload.get("mcp_method") or "",
        "mcp_tool_name": payload.get("mcp_tool_name") or "",
        "request_preview": _to_preview(request_payload),
        "response_preview": _to_preview(response_payload),
        "request_payload": request_payload,
        "response_payload": response_payload,
        "raw": payload,
    }


async def fetch_context_events_from_loki(context_id: str, run_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    query = f'{{context_id="{context_id}"}} | json'
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - (7 * 24 * 60 * 60 * 1_000_000_000)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            LOKI_QUERY_URL,
            params={
                "query": query,
                "limit": min(max(limit, 1), 2000),
                "direction": "forward",
                "start": str(start_ns),
                "end": str(end_ns),
            },
        )
        response.raise_for_status()
        data = response.json()
    events: list[dict[str, Any]] = []
    for stream in data.get("data", {}).get("result", []):
        for ts_ns, raw_line in stream.get("values", []):
            event = _normalize_loki_event(ts_ns, raw_line)
            if run_id and event["run_id"] != run_id:
                continue
            events.append(event)
    events.sort(key=lambda item: item["timestamp_ns"])
    return events


@app.get("/health")
@app.get("/orchestrator/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/agent-card.json")
@app.get("/orchestrator/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
@app.get("/orchestrator/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    return {
        "agent_id": "orchestrator",
        "name": "Orchestrator",
        "description": "Coordinates the customer escalation triage workflow.",
        "url": "http://orchestrator:8000/v1/jsonrpc",
        "additionalInterfaces": [
            {"kind": "jsonrpc", "url": "http://orchestrator:8000/v1/jsonrpc"},
        ],
        "endpoints": {"jsonrpc": "/v1/jsonrpc", "a2a": "/v1/jsonrpc"},
    }


@app.post("/play")
@app.post("/orchestrator/play")
async def play(request: Request, payload: PlayRequest) -> dict[str, Any]:
    trace_token = set_trace_headers_from_request(request)
    try:
        return await run_playbook(payload)
    finally:
        reset_trace_headers(trace_token)


@app.post("/semantic-cache/clear")
@app.post("/orchestrator/semantic-cache/clear")
async def clear_semantic_cache() -> dict[str, Any]:
    result = await clear_semantic_cache_keys()
    return {
        "status": "cleared",
        **result,
    }


@app.post("/observability/reset")
@app.post("/orchestrator/observability/reset")
async def reset_observability() -> dict[str, Any]:
    result = await reset_observability_stack()
    return {
        "status": "reset",
        **result,
    }


@app.post("/v1/jsonrpc")
@app.post("/orchestrator/v1/jsonrpc")
async def jsonrpc_endpoint(request: Request) -> dict[str, Any]:
    trace_token = set_trace_headers_from_request(request)
    body = await request.json()
    try:
        request_id = body.get("id")
        method = body.get("method")
        if method not in {"agent.run", "message/send"}:
            return error_response(request_id, -32601, "Unsupported method")
        try:
            params = PlayRequest.model_validate(body.get("params", {}))
        except Exception:
            payload = body.get("params", {})
            message = payload.get("message") if isinstance(payload, dict) else {}
            message_text = extract_message_text(message)
            if not message_text:
                return error_response(request_id, -32602, "Invalid params", "Unable to extract play payload from A2A message")
            try:
                params = PlayRequest.model_validate(json.loads(message_text))
            except Exception as exc:
                return error_response(request_id, -32602, "Invalid params", str(exc))
        try:
            result = await run_playbook(params)
        except Exception as exc:
            return error_response(request_id, -32000, "Orchestrator failed", str(exc))
        return success_response(request_id, result)
    finally:
        reset_trace_headers(trace_token)


@app.post("/trace/event")
async def trace_event(event: ExternalTraceEvent) -> dict[str, str]:
    await emit(event.run_id, event.type, **event.payload)
    return {"status": "accepted"}


@app.get("/trace/runs")
@app.get("/orchestrator/trace/runs")
async def trace_runs() -> dict[str, list[dict[str, Any]]]:
    return {"runs": await trace_broker.list_runs()}


@app.get("/trace/runs/{run_id}")
@app.get("/orchestrator/trace/runs/{run_id}")
async def trace_run(run_id: str) -> dict[str, Any]:
    run = await trace_broker.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/trace/context/{context_id}/events")
@app.get("/orchestrator/trace/context/{context_id}/events")
async def trace_context_events(context_id: str, run_id: str | None = None, limit: int = 500) -> dict[str, Any]:
    events = await fetch_context_events_from_loki(context_id, run_id=run_id, limit=limit)
    return {
        "context_id": context_id,
        "run_id": run_id,
        "event_count": len(events),
        "events": events,
    }


@app.websocket("/trace")
@app.websocket("/orchestrator/trace")
async def trace_socket(websocket: WebSocket) -> None:
    await trace_broker.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await trace_broker.disconnect(websocket)
