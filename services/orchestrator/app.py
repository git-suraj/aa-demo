from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from typing import TypedDict

import httpx
from openai import APIStatusError, AuthenticationError, RateLimitError
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
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


class PlayRequest(BaseModel):
    customer_id: str = "cust_acme"
    account_name: str = "Acme Health"
    issue_summary: str = "Customer reports a billing dispute and workflow-agent sync delays."
    product_issue: str = "workflow agent sync delays"
    billing_issue: str = "billing overcharge on enterprise add-ons"
    incident_id: str = "INC-1007"
    governance_scenario: str = "normal"


class ExternalTraceEvent(BaseModel):
    run_id: str
    type: str
    payload: dict[str, Any] = {}


class OrchestratorState(TypedDict, total=False):
    request: dict[str, Any]
    run_id: str
    governance_scenario: str
    ai_route_base_url: str
    available_tools: list[str]
    selected_tools: list[str]
    tool_plan: dict[str, Any]
    tool_plan_steps: list[dict[str, Any]]
    account_context: Any
    renewal_risk: Any
    open_tickets: Any
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


def ai_route_for_scenario(scenario: str) -> str:
    route_map = {
        "normal": f"{KONG_PROXY_URL}/ai/orchestrator",
        "llm_failover": f"{KONG_PROXY_URL}/ai/orchestrator-failover-demo",
        "token_limit": f"{KONG_PROXY_URL}/ai/orchestrator-token-demo",
        "prompt_enhancement": f"{KONG_PROXY_URL}/ai/orchestrator-prompt-enhance-demo",
        "semantic_guard": f"{KONG_PROXY_URL}/ai/orchestrator-semantic-guard-demo",
    }
    return route_map.get(scenario, route_map["normal"])


def scenario_summary(scenario: str) -> str:
    summaries = {
        "normal": "Standard Kong-governed orchestration flow.",
        "llm_failover": "OpenAI primary is expected to fail and Kong should fail over to Gemini.",
        "token_limit": "Kong AI token governance is expected to block a later orchestrator LLM call.",
        "prompt_enhancement": "Kong prompt decoration applies stronger executive-governance instructions so the orchestrator output becomes more structured and enterprise-safe.",
        "semantic_guard": "Kong semantic guard is expected to block prompts that request sensitive personal or internal system information.",
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
        return await llm.generate(base_url=base_url, **prompts)
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


async def discover_agent(route_prefix: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{KONG_PROXY_URL}{route_prefix}/.well-known/agent.json",
            headers={"apikey": AGENT_API_KEY},
        )
        response.raise_for_status()
        return response.json()


async def call_subagent(route_prefix: str, params: dict[str, Any]) -> dict[str, Any]:
    card = await discover_agent(route_prefix)
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
            headers={"apikey": AGENT_API_KEY},
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
    mcp = KongMCPClient(f"{KONG_PROXY_URL}/mock-mcp", AGENT_API_KEY, "orchestrator")
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
    await emit(run_id, "llm_started", actor="orchestrator", stage="triage_plan", input=llm_input)
    started = time.perf_counter()
    triage_prompts = llm_input
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
        stage="triage_plan",
        llm_used=triage_brief["llm_used"],
        model=triage_brief["model"],
        output=triage_brief,
        duration_ms=timed_ms(started),
    )
    return {"triage_brief": triage_brief}


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
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    scenario = request.governance_scenario
    ai_route_base_url = ai_route_for_scenario(scenario)
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
    try:
        graph_result = await orchestrator_graph.ainvoke(
            {
                "request": request.model_dump(),
                "run_id": run_id,
                "governance_scenario": scenario,
                "ai_route_base_url": ai_route_base_url,
            }
        )
    except (RateLimitError, APIStatusError) as exc:
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


@app.websocket("/trace")
@app.websocket("/orchestrator/trace")
async def trace_socket(websocket: WebSocket) -> None:
    await trace_broker.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await trace_broker.disconnect(websocket)
