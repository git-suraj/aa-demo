from __future__ import annotations

import os
import time
from typing import Any
from typing import TypedDict

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel
from langgraph.graph import END, START, StateGraph

from services.common.jsonrpc import error_response, success_response
from services.common.llm import OrchestratorLLM
from services.common.mcp_client import KongMCPClient


app = FastAPI(title="Success Agent", version="1.0.0")

MCP_URL = os.getenv("KONG_MCP_URL", "http://kong-dp:8000/mock-mcp")
API_KEY = os.getenv("AGENT_API_KEY", "success-demo-key")
TRACE_COLLECTOR_URL = os.getenv("TRACE_COLLECTOR_URL", "http://orchestrator:8000/trace/event")
os.environ.setdefault("KONG_AI_PROXY_URL", "http://kong-dp:8000/ai/subagent")
llm = OrchestratorLLM()


class SuccessRunParams(BaseModel):
    run_id: str
    account_name: str
    csm: str
    issue_summary: str
    renewal_risk: str
    technical_summary: str
    triage_brief: str


class SuccessState(TypedDict, total=False):
    params: dict[str, Any]
    available_tools: list[str]
    called_mcp_tools: list[str]
    tool_plan_steps: list[dict[str, Any]]
    customer_reply: Any
    followup_task: Any
    llm_summary: dict[str, Any]
    result: dict[str, Any]


async def emit_trace(run_id: str, event_type: str, **payload: Any) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            TRACE_COLLECTOR_URL,
            json={"run_id": run_id, "type": event_type, "payload": payload},
        )


async def fetch_tool_inventory(state: SuccessState) -> SuccessState:
    params = state["params"]
    client = KongMCPClient(MCP_URL, API_KEY, "success-agent", run_id=params["run_id"])
    started = time.perf_counter()
    tools = await client.list_tools()
    available_tools = [tool.get("name") for tool in tools]
    await emit_trace(
        params["run_id"],
        "tool_list_received",
        actor="success-agent",
        tools=available_tools,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return {"available_tools": available_tools}


def unwrap_mcp_result(result: Any) -> Any:
    if isinstance(result, dict):
        return result.get("structuredContent") or result.get("content") or result
    return result


def build_success_tool_args(tool_name: str, llm_arguments: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "draft_customer_reply":
        return {
            "query_account_name": llm_arguments.get("account_name") or llm_arguments.get("query_account_name") or params["account_name"],
            "query_csm": llm_arguments.get("csm") or llm_arguments.get("query_csm") or params["csm"],
            "query_issue_summary": llm_arguments.get("issue_summary") or llm_arguments.get("query_issue_summary") or params["issue_summary"],
            "query_renewal_risk": llm_arguments.get("renewal_risk") or llm_arguments.get("query_renewal_risk") or params["renewal_risk"],
            "query_technical_summary": llm_arguments.get("technical_summary") or llm_arguments.get("query_technical_summary") or params["technical_summary"],
        }
    if tool_name == "create_followup_task":
        return {
            "query_account_name": llm_arguments.get("account_name") or llm_arguments.get("query_account_name") or params["account_name"],
            "query_owner": llm_arguments.get("owner") or llm_arguments.get("query_owner") or params["csm"],
            "query_due_date": llm_arguments.get("due_date") or llm_arguments.get("query_due_date") or "2026-03-31",
            "query_action_items": llm_arguments.get("action_items")
            or llm_arguments.get("query_action_items")
            or ",".join(
                [
                    "Schedule executive follow-up",
                    "Confirm billing correction",
                    "Track product mitigation until resolved",
                ]
            ),
        }
    return llm_arguments


async def prepare_customer_actions(state: SuccessState) -> SuccessState:
    params = state["params"]
    client = KongMCPClient(MCP_URL, API_KEY, "success-agent", run_id=params["run_id"])
    available_tools = state.get("available_tools", [])
    remaining_tools = [tool for tool in available_tools if tool in {"draft_customer_reply", "create_followup_task"}]
    called_mcp_tools: list[str] = []
    tool_plan_steps: list[dict[str, Any]] = []
    reply = None
    task = None

    for step_number in range(1, len(remaining_tools) + 2):
        current_context = {
            "customer_reply": unwrap_mcp_result(reply) if reply else None,
            "followup_task": unwrap_mcp_result(task) if task else None,
            "technical_summary": params["technical_summary"],
            "renewal_risk": params["renewal_risk"],
        }
        prompts = llm.build_next_tool_prompts(
            account_name=params["account_name"],
            issue_summary=params["issue_summary"],
            product_issue=params["technical_summary"],
            billing_issue=params["renewal_risk"],
            available_tools=available_tools,
            remaining_tools=remaining_tools,
            current_context=current_context,
        )
        stage = f"tool_selection_{step_number}"
        await emit_trace(params["run_id"], "llm_started", actor="success-agent", stage=stage, input=prompts)
        started = time.perf_counter()
        tool_decision = await llm.choose_next_tool(
            account_name=params["account_name"],
            issue_summary=params["issue_summary"],
            product_issue=params["technical_summary"],
            billing_issue=params["renewal_risk"],
            available_tools=available_tools,
            remaining_tools=remaining_tools,
            current_context=current_context,
        )
        await emit_trace(
            params["run_id"],
            "llm_completed",
            actor="success-agent",
            stage=stage,
            llm_used=tool_decision["llm_used"],
            model=tool_decision["model"],
            output=tool_decision,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        tool_plan_steps.append(tool_decision)

        next_tool = tool_decision.get("next_tool")
        if tool_decision.get("done") or not next_tool or next_tool not in remaining_tools:
            break

        tool_args = build_success_tool_args(next_tool, tool_decision.get("arguments", {}), params)
        await emit_trace(params["run_id"], "tool_call_started", actor="success-agent", tool=next_tool, input=tool_args)
        tool_started = time.perf_counter()
        tool_result = await client.call_tool(next_tool, tool_args)
        await emit_trace(
            params["run_id"],
            "tool_call_completed",
            actor="success-agent",
            tool=next_tool,
            input=tool_args,
            output=tool_result,
            duration_ms=round((time.perf_counter() - tool_started) * 1000),
        )

        if next_tool == "draft_customer_reply":
            reply = tool_result
        elif next_tool == "create_followup_task":
            task = tool_result
        called_mcp_tools.append(next_tool)
        remaining_tools.remove(next_tool)

        if not remaining_tools:
            break

    return {
        "called_mcp_tools": called_mcp_tools,
        "tool_plan_steps": tool_plan_steps,
        "customer_reply": unwrap_mcp_result(reply) if reply else None,
        "followup_task": unwrap_mcp_result(task) if task else None,
    }


async def generate_success_summary(state: SuccessState) -> SuccessState:
    params = state["params"]
    customer_reply = state.get("customer_reply")
    followup_task = state.get("followup_task")
    system_prompt = "You are a customer success sub-agent. Produce a concise executive-ready communication plan."
    user_prompt = (
        f"Triage brief: {params['triage_brief']}\n"
        f"Issue summary: {params['issue_summary']}\n"
        f"Renewal risk: {params['renewal_risk']}\n"
        f"Technical summary: {params['technical_summary']}\n"
        f"Draft reply: {customer_reply}\n"
        f"Follow-up task: {followup_task}\n"
        "Write 2 short paragraphs: customer posture and next account-team actions."
    )
    llm_input = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    await emit_trace(params["run_id"], "llm_started", actor="success-agent", stage="success_summary", input=llm_input)
    started = time.perf_counter()
    if not llm.enabled:
        result = {
            "llm_summary": {
                "llm_used": False,
                "model": None,
                "summary": (
                    f"Customer success view for {params['account_name']}: send the prepared reply, "
                    f"track the follow-up task, and keep updates tied to the technical summary."
                ),
            }
        }
        await emit_trace(
            params["run_id"],
            "llm_completed",
            actor="success-agent",
            stage="success_summary",
            llm_used=False,
            model=None,
            output=result["llm_summary"],
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return result
    llm_summary = await llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            run_id=params["run_id"],
        )
    await emit_trace(
        params["run_id"],
        "llm_completed",
        actor="success-agent",
        stage="success_summary",
        llm_used=llm_summary["llm_used"],
        model=llm_summary["model"],
        output=llm_summary,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return {"llm_summary": llm_summary}


def build_response(state: SuccessState) -> SuccessState:
    result = {
        "agent": "success-agent",
        "triage_brief": state["params"]["triage_brief"],
        "available_tools": state.get("available_tools", []),
        "called_mcp_tools": state.get("called_mcp_tools", []),
        "tool_plan_steps": state.get("tool_plan_steps", []),
        "customer_reply": state.get("customer_reply"),
        "followup_task": state.get("followup_task"),
        "llm_summary": state.get("llm_summary"),
        "success_plan": [
            "Send a same-day executive response",
            "Assign a named owner for billing correction",
            "Keep a daily cadence until the customer confirms stability",
        ],
    }
    return {"result": result}


success_graph = (
    StateGraph(SuccessState)
    .add_node("fetch_tool_inventory", fetch_tool_inventory)
    .add_node("prepare_customer_actions", prepare_customer_actions)
    .add_node("generate_success_summary", generate_success_summary)
    .add_node("build_response", build_response)
    .add_edge(START, "fetch_tool_inventory")
    .add_edge("fetch_tool_inventory", "prepare_customer_actions")
    .add_edge("prepare_customer_actions", "generate_success_summary")
    .add_edge("generate_success_summary", "build_response")
    .add_edge("build_response", END)
    .compile()
)


@app.get("/health")
@app.get("/success-agent/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/agent.json")
@app.get("/success-agent/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    return {
        "agent_id": "success-agent",
        "name": "Success Agent",
        "description": "Builds the customer communication and success-team follow-up plan.",
        "endpoints": {"jsonrpc": "/v1/jsonrpc"},
    }


@app.post("/v1/jsonrpc")
@app.post("/success-agent/v1/jsonrpc")
async def jsonrpc_endpoint(request: Request) -> dict[str, Any]:
    body = await request.json()
    request_id = body.get("id")
    if body.get("method") != "agent.run":
        return error_response(request_id, -32601, "Unsupported method")

    try:
        params = SuccessRunParams.model_validate(body.get("params", {}))
    except Exception as exc:
        return error_response(request_id, -32602, "Invalid params", str(exc))

    try:
        graph_result = await success_graph.ainvoke({"params": params.model_dump()})
    except Exception as exc:
        return error_response(request_id, -32000, "Success agent failed", str(exc))
    return success_response(request_id, graph_result["result"])
