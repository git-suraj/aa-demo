from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from typing import TypedDict

import httpx
import redis.asyncio as redis
from openai import APIStatusError, AuthenticationError, RateLimitError
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from services.common.jsonrpc import error_response, success_response
from services.common.llm import OrchestratorLLM
from services.common.mcp_client import KongMCPClient
from services.common.trace import TraceBroker


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
SUBAGENT_DISCOVERY_ATTEMPTS = 3
SUBAGENT_DISCOVERY_BACKOFF_MS = 350


class PlayRequest(BaseModel):
    run_id: str | None = None
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
    await trace_broker.broadcast(
        {
            "run_id": run_id,
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
    )


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
    stage: str,
    scenario: str,
    prompts: dict[str, str],
    available_tools: list[str],
    remaining_tools: list[str],
    base_url: str,
) -> dict[str, Any]:
    response = await generate_for_scenario(
        run_id=run_id,
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
    stage: str,
    scenario: str,
    prompts: dict[str, str],
    base_url: str,
) -> dict[str, Any]:
    try:
        return await llm.generate(base_url=base_url, run_id=run_id, **prompts)
    except httpx.HTTPStatusError as exc:
        if scenario == "token_limit" and exc.response.status_code == 429:
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
            return await llm.generate(
                base_url=GEMINI_FALLBACK_URL,
                model=GEMINI_FALLBACK_MODEL,
                run_id=run_id,
                **prompts,
            )
        raise
    except AuthenticationError as exc:
        if scenario != "llm_failover":
            raise
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
        fallback = await llm.generate(
            base_url=GEMINI_FALLBACK_URL,
            model=GEMINI_FALLBACK_MODEL,
            run_id=run_id,
            **prompts,
        )
        return fallback
    except RateLimitError as exc:
        if scenario == "token_limit":
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


async def discover_agent(route_prefix: str, run_id: str | None = None) -> dict[str, Any]:
    headers = {
        "apikey": AGENT_API_KEY,
        **({"x-demo-run-id": run_id} if run_id else {}),
    }
    last_error: Exception | None = None

    for attempt in range(1, SUBAGENT_DISCOVERY_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{KONG_PROXY_URL}{route_prefix}/.well-known/agent.json",
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
    card = await discover_agent(route_prefix, run_id=run_id)
    endpoint = card["endpoints"]["jsonrpc"]
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "agent.run",
        "params": params,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{KONG_PROXY_URL}{route_prefix}{endpoint}",
            headers={
                "apikey": AGENT_API_KEY,
                **({"x-demo-run-id": run_id} if run_id else {}),
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"]["message"])
    return {"card": card, "result": data["result"]}


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
    mcp = KongMCPClient(f"{KONG_PROXY_URL}/mock-mcp", AGENT_API_KEY, "orchestrator", run_id=run_id)
    await emit(run_id, "planning", message="Fetching account context through Kong MCP.")
    list_started = time.perf_counter()
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
            ) if ai_route_base_url == llm.base_url else await choose_next_tool_for_route(
                run_id=run_id,
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
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage_name, input=llm_input)
        started = time.perf_counter()
        triage_brief = await llm.generate_with_headers(base_url=ai_route_base_url, run_id=run_id, **triage_prompts)
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
    else:
        await emit(run_id, "llm_started", actor="orchestrator", stage="triage_plan", input=llm_input)
        started = time.perf_counter()
        triage_brief = await generate_for_scenario(
            run_id=run_id,
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
    request = state["request"]
    params = {
        "run_id": run_id,
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
    request = state["request"]
    support_track = state.get("support_track", {})
    params = {
        "run_id": run_id,
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
    )
    await emit(
        run_id,
        "scenario_selected",
        actor="orchestrator",
        scenario=scenario,
        summary=scenario_summary(scenario),
        output={"ai_route_base_url": ai_route_base_url},
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
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage, input=prompts)
        llm_started = time.perf_counter()
        try:
            pii_result = await llm.generate_with_headers(base_url=ai_route_base_url, run_id=run_id, **prompts)
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
            await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=blocked_response)
            return {"run_id": run_id, "result": blocked_response}
        pii_output = without_cache_headers(pii_result)
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
            llm_used=pii_output["llm_used"],
            model=pii_output["model"],
            output=pii_output,
            duration_ms=timed_ms(llm_started),
        )
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
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=final_response)
        return {"run_id": run_id, "result": final_response}
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
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage, input=prompts)
        llm_started = time.perf_counter()
        judge_result = await llm.generate_with_headers(
            base_url=ai_route_base_url,
            model="gpt-4o-mini",
            run_id=run_id,
            **prompts,
        )
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
            llm_used=judge_result["llm_used"],
            model=judge_result["model"],
            output=judge_result,
            duration_ms=timed_ms(llm_started),
        )
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
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=final_response)
        return {"run_id": run_id, "result": final_response}
    if scenario == "semantic_cache":
        prompts = build_semantic_cache_prompts(request)
        stage = "semantic_cache_seed" if semantic_cache_step == "seed" else "semantic_cache_reuse"
        stage_summary = (
            "First semantic-cache request through Kong. This should populate Redis."
            if semantic_cache_step == "seed"
            else "Second semantic-cache request through Kong. This should reuse the cached response."
        )
        await emit(run_id, "planning", message=stage_summary)
        await emit(run_id, "llm_started", actor="orchestrator", stage=stage, input=prompts)
        llm_started = time.perf_counter()
        triage_result = await llm.generate_with_headers(base_url=ai_route_base_url, run_id=run_id, **prompts)
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
        await emit(
            run_id,
            "llm_completed",
            actor="orchestrator",
            stage=stage,
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
        await emit(run_id, "final_response", headline=final_response["headline"], output=final_response)
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=final_response)
        return {"run_id": run_id, "result": final_response}
    try:
        graph_result = await orchestrator_graph.ainvoke(
            {
                "request": request.model_dump(),
                "run_id": run_id,
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
        await emit(run_id, "final_response", headline=blocked_result["headline"], output=blocked_result)
        await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=blocked_result)
        return {"run_id": run_id, "result": blocked_result}
    await emit(run_id, "run_completed", duration_ms=timed_ms(started), output=graph_result["result"])
    return {"run_id": run_id, "result": graph_result["result"]}


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


@app.get("/health")
@app.get("/orchestrator/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/agent.json")
@app.get("/orchestrator/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    return {
        "agent_id": "orchestrator",
        "name": "Orchestrator",
        "description": "Coordinates the customer escalation triage workflow.",
        "endpoints": {"jsonrpc": "/v1/jsonrpc"},
    }


@app.post("/play")
@app.post("/orchestrator/play")
async def play(request: PlayRequest) -> dict[str, Any]:
    return await run_playbook(request)


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
    body = await request.json()
    request_id = body.get("id")
    if body.get("method") != "agent.run":
        return error_response(request_id, -32601, "Unsupported method")
    try:
        params = PlayRequest.model_validate(body.get("params", {}))
    except Exception as exc:
        return error_response(request_id, -32602, "Invalid params", str(exc))
    try:
        result = await run_playbook(params)
    except Exception as exc:
        return error_response(request_id, -32000, "Orchestrator failed", str(exc))
    return success_response(request_id, result)


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


@app.websocket("/trace")
@app.websocket("/orchestrator/trace")
async def trace_socket(websocket: WebSocket) -> None:
    await trace_broker.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await trace_broker.disconnect(websocket)
