from __future__ import annotations

import asyncio
import json
import os
import time
from contextvars import ContextVar
from typing import Any
from typing import TypedDict

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langgraph.graph import END, START, StateGraph

from services.common.jsonrpc import error_response, success_response
from services.common.a2a import extract_message_text
from services.common.a2a import new_task_id
from services.common.a2a_tasks import A2ATaskStore, TERMINAL_TASK_STATES
from services.common.llm import OrchestratorLLM
from services.common.mcp_client import KongMCPClient


app = FastAPI(title="Support Agent", version="1.0.0")

MCP_URL = os.getenv("KONG_MCP_URL", "http://kong-dp:8000/mock-mcp")
API_KEY = os.getenv("AGENT_API_KEY", "support-demo-key")
TRACE_COLLECTOR_URL = os.getenv("TRACE_COLLECTOR_URL", "http://orchestrator:8000/trace/event")
os.environ.setdefault("KONG_AI_PROXY_URL", "http://kong-dp:8000/ai/subagent")
llm = OrchestratorLLM()
CURRENT_CONTEXT_ID: ContextVar[str | None] = ContextVar("support_context_id", default=None)
CURRENT_TASK_ID: ContextVar[str | None] = ContextVar("support_task_id", default=None)
CURRENT_MESSAGE_ID: ContextVar[str | None] = ContextVar("support_message_id", default=None)
TASK_STORE = A2ATaskStore("support-agent")
RUNNING_TASKS: dict[str, asyncio.Task[Any]] = {}


class SupportRunParams(BaseModel):
    run_id: str
    context_id: str
    task_id: str | None = None
    customer_id: str
    account_name: str
    product_issue: str
    incident_id: str
    triage_brief: str


class SupportState(TypedDict, total=False):
    params: dict[str, Any]
    available_tools: list[str]
    called_mcp_tools: list[str]
    tool_plan_steps: list[dict[str, Any]]
    incident: Any
    runbook: Any
    llm_summary: dict[str, Any]
    result: dict[str, Any]


async def emit_trace(run_id: str, event_type: str, **payload: Any) -> None:
    payload.setdefault("context_id", CURRENT_CONTEXT_ID.get())
    payload.setdefault("task_id", CURRENT_TASK_ID.get())
    payload.setdefault("message_id", CURRENT_MESSAGE_ID.get())
    task_id = payload.get("task_id")
    if task_id:
        await TASK_STORE.append_history(
            str(task_id),
            event_type,
            actor=payload.get("actor"),
            stage=payload.get("stage"),
            tool=payload.get("tool"),
            component=payload.get("component"),
            duration_ms=payload.get("duration_ms"),
        )
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            TRACE_COLLECTOR_URL,
            json={"run_id": run_id, "type": event_type, "payload": payload},
        )


async def fetch_tool_inventory(state: SupportState) -> SupportState:
    params = state["params"]
    client = KongMCPClient(
        MCP_URL,
        API_KEY,
        "support-agent",
        run_id=params["run_id"],
        context_id=params["context_id"],
        task_id=params.get("task_id"),
        message_id=params.get("message_id"),
    )
    started = time.perf_counter()
    await emit_trace(params["run_id"], "tool_list_started", actor="support-agent")
    tools = await client.list_tools()
    available_tools = [tool.get("name") for tool in tools]
    await emit_trace(
        params["run_id"],
        "tool_list_received",
        actor="support-agent",
        tools=available_tools,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return {"available_tools": available_tools}


def unwrap_mcp_result(result: Any) -> Any:
    if isinstance(result, dict):
        return result.get("structuredContent") or result.get("content") or result
    return result


def build_support_tool_args(tool_name: str, llm_arguments: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "get_incident_status":
        incident_id = llm_arguments.get("incident_id") or llm_arguments.get("path_incident_id") or params["incident_id"]
        return {"path_incident_id": incident_id}
    if tool_name == "search_runbook":
        query = llm_arguments.get("q") or llm_arguments.get("query_q") or params["product_issue"]
        return {"query_q": query}
    return llm_arguments


async def investigate_issue(state: SupportState) -> SupportState:
    params = state["params"]
    client = KongMCPClient(
        MCP_URL,
        API_KEY,
        "support-agent",
        run_id=params["run_id"],
        context_id=params["context_id"],
        task_id=params.get("task_id"),
        message_id=params.get("message_id"),
    )
    available_tools = state.get("available_tools", [])
    remaining_tools = [tool for tool in available_tools if tool in {"get_incident_status", "search_runbook"}]
    called_mcp_tools: list[str] = []
    tool_plan_steps: list[dict[str, Any]] = []
    incident = None
    runbook = None

    for step_number in range(1, len(remaining_tools) + 2):
        current_context = {
            "incident": unwrap_mcp_result(incident) if incident else None,
            "runbook": unwrap_mcp_result(runbook) if runbook else None,
        }
        prompts = llm.build_next_tool_prompts(
            account_name=params["account_name"],
            issue_summary=params["triage_brief"],
            product_issue=params["product_issue"],
            billing_issue="n/a",
            available_tools=available_tools,
            remaining_tools=remaining_tools,
            current_context=current_context,
        )
        stage = f"tool_selection_{step_number}"
        await emit_trace(params["run_id"], "llm_started", actor="support-agent", stage=stage, component="gemini", input=prompts)
        started = time.perf_counter()
        tool_decision = await llm.choose_next_tool(
            account_name=params["account_name"],
            issue_summary=params["triage_brief"],
            product_issue=params["product_issue"],
            billing_issue="n/a",
            available_tools=available_tools,
            remaining_tools=remaining_tools,
            current_context=current_context,
            run_id=params["run_id"],
            context_id=params["context_id"],
            task_id=params.get("task_id"),
            message_id=params.get("message_id"),
        )
        await emit_trace(
            params["run_id"],
            "llm_completed",
            actor="support-agent",
            stage=stage,
            component="gemini",
            llm_used=tool_decision["llm_used"],
            model=tool_decision["model"],
            output=tool_decision,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        tool_plan_steps.append(tool_decision)

        next_tool = tool_decision.get("next_tool")
        if tool_decision.get("done") or not next_tool or next_tool not in remaining_tools:
            break

        tool_args = build_support_tool_args(next_tool, tool_decision.get("arguments", {}), params)
        await emit_trace(params["run_id"], "tool_call_started", actor="support-agent", tool=next_tool, input=tool_args)
        tool_started = time.perf_counter()
        tool_result = await client.call_tool(next_tool, tool_args)
        await emit_trace(
            params["run_id"],
            "tool_call_completed",
            actor="support-agent",
            tool=next_tool,
            input=tool_args,
            output=tool_result,
            duration_ms=round((time.perf_counter() - tool_started) * 1000),
        )

        if next_tool == "get_incident_status":
            incident = tool_result
        elif next_tool == "search_runbook":
            runbook = tool_result
        called_mcp_tools.append(next_tool)
        remaining_tools.remove(next_tool)

        if not remaining_tools:
            break

    return {
        "called_mcp_tools": called_mcp_tools,
        "tool_plan_steps": tool_plan_steps,
        "incident": unwrap_mcp_result(incident) if incident else None,
        "runbook": unwrap_mcp_result(runbook) if runbook else None,
    }


async def generate_technical_summary(state: SupportState) -> SupportState:
    params = state["params"]
    incident = state.get("incident")
    runbook = state.get("runbook")
    system_prompt = "You are a support engineering sub-agent. Produce a concise technical customer escalation summary."
    user_prompt = (
        f"Triage brief: {params['triage_brief']}\n"
        f"Product issue: {params['product_issue']}\n"
        f"Incident: {incident}\n"
        f"Runbook: {runbook}\n"
        "Write 2 short paragraphs: current technical posture and immediate remediation plan."
    )
    llm_input = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
    await emit_trace(params["run_id"], "llm_started", actor="support-agent", stage="technical_summary", component="gemini", input=llm_input)
    started = time.perf_counter()
    if not llm.enabled:
        result = {
            "llm_summary": {
                "llm_used": False,
                "model": None,
                "summary": (
                    f"Technical view for {params['account_name']}: align the customer update to the "
                    f"incident status {incident} and the operational guidance {runbook}."
                ),
            }
        }
        await emit_trace(
            params["run_id"],
            "llm_completed",
            actor="support-agent",
            stage="technical_summary",
            component="gemini",
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
            context_id=params["context_id"],
            task_id=params.get("task_id"),
            message_id=params.get("message_id"),
        )
    await emit_trace(
        params["run_id"],
        "llm_completed",
        actor="support-agent",
        stage="technical_summary",
        component="gemini",
        llm_used=llm_summary["llm_used"],
        model=llm_summary["model"],
        output=llm_summary,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return {"llm_summary": llm_summary}


def build_response(state: SupportState) -> SupportState:
    params = state["params"]
    result = {
        "agent": "support-agent",
        "context_id": params["context_id"],
        "task_id": params.get("task_id"),
        "triage_brief": params["triage_brief"],
        "available_tools": state.get("available_tools", []),
        "called_mcp_tools": state.get("called_mcp_tools", []),
        "tool_plan_steps": state.get("tool_plan_steps", []),
        "incident": state.get("incident"),
        "runbook": state.get("runbook"),
        "llm_summary": state.get("llm_summary"),
        "technical_response": state.get("llm_summary", {}).get(
            "summary",
            (
                f"The current incident is being actively mitigated for {params['account_name']}. "
                "Recommend acknowledging the impact, confirming engineering ownership, and sharing "
                "the mitigation ETA plus the next status checkpoint."
            ),
        ),
        "recommended_actions": [
            "Share the current incident status and ETA",
            "Reference the runbook-driven mitigation path",
            "Keep the escalation open until sync latency returns to normal",
        ],
    }
    return {"result": result}


support_graph = (
    StateGraph(SupportState)
    .add_node("fetch_tool_inventory", fetch_tool_inventory)
    .add_node("investigate_issue", investigate_issue)
    .add_node("generate_technical_summary", generate_technical_summary)
    .add_node("build_response", build_response)
    .add_edge(START, "fetch_tool_inventory")
    .add_edge("fetch_tool_inventory", "investigate_issue")
    .add_edge("investigate_issue", "generate_technical_summary")
    .add_edge("generate_technical_summary", "build_response")
    .add_edge("build_response", END)
    .compile()
)


@app.get("/health")
@app.get("/support-agent/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/agent-card.json")
@app.get("/support-agent/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
@app.get("/support-agent/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    return {
        "agent_id": "support-agent",
        "name": "Support Agent",
        "description": "Investigates technical issues and recommends remediation steps.",
        "url": "http://support-agent:8000/a2a",
        "additionalInterfaces": [
            {"kind": "a2a", "url": "http://support-agent:8000/a2a"},
            {"kind": "jsonrpc", "url": "http://support-agent:8000/v1/jsonrpc"},
        ],
        "endpoints": {"jsonrpc": "/v1/jsonrpc", "a2a": "/a2a"},
    }


@app.post("/v1/jsonrpc")
@app.post("/support-agent/v1/jsonrpc")
@app.post("/a2a")
@app.post("/support-agent/a2a")
async def jsonrpc_endpoint(request: Request) -> dict[str, Any]:
    body = await request.json()
    request_id = body.get("id")
    method = body.get("method")
    if method not in {"agent.run", "message/send", "message/stream", "tasks/get"}:
        return error_response(request_id, -32601, "Unsupported method")

    if method == "tasks/get":
        payload = body.get("params", {})
        task_id = None
        if isinstance(payload, dict):
            task_id = payload.get("id") or payload.get("taskId") or payload.get("task_id")
        if not task_id:
            return error_response(request_id, -32602, "Invalid params", "Missing task id")
        task = await TASK_STORE.get(str(task_id))
        if not task:
            return error_response(request_id, -32004, "Task not found")
        return success_response(request_id, task)

    try:
        params = SupportRunParams.model_validate(body.get("params", {}))
    except Exception as exc:
        if method not in {"message/send", "message/stream"}:
            return error_response(request_id, -32602, "Invalid params", str(exc))
        payload = body.get("params", {})
        message = payload.get("message") if isinstance(payload, dict) else {}
        message_text = extract_message_text(message)
        if not message_text:
            return error_response(request_id, -32602, "Invalid params", "Unable to extract A2A message payload")
        try:
            params = SupportRunParams.model_validate(json.loads(message_text))
        except Exception as inner_exc:
            return error_response(request_id, -32602, "Invalid params", str(inner_exc))

    payload = body.get("params", {})
    message = payload.get("message") if isinstance(payload, dict) else {}
    inbound_message_id = message.get("messageId") if isinstance(message, dict) else None
    if method in {"message/send", "message/stream"}:
        task_id = params.task_id or (payload.get("task_id") if isinstance(payload, dict) else None) or new_task_id()
        task = await TASK_STORE.upsert_inbound_message(
            task_id=task_id,
            context_id=params.context_id,
            run_id=params.run_id,
            message=message if isinstance(message, dict) else {},
            metadata={"run_id": params.run_id},
        )
        if task_id not in RUNNING_TASKS or RUNNING_TASKS[task_id].done():
            RUNNING_TASKS[task_id] = asyncio.create_task(
                execute_support_task(
                    task_id=task_id,
                    params={**params.model_dump(), "task_id": task_id, "message_id": inbound_message_id},
                )
            )
        if method == "message/send":
            return success_response(request_id, task)
        queue = await TASK_STORE.subscribe(task_id)

        async def event_stream():
            try:
                while True:
                    snapshot = await queue.get()
                    envelope = {"jsonrpc": "2.0", "id": request_id, "result": snapshot}
                    yield f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n"
                    state = str(snapshot.get("status", {}).get("state") or "unknown")
                    if state in TERMINAL_TASK_STATES:
                        break
            finally:
                await TASK_STORE.unsubscribe(task_id, queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    context_token = CURRENT_CONTEXT_ID.set(params.context_id)
    task_token = CURRENT_TASK_ID.set(params.task_id)
    message_token = CURRENT_MESSAGE_ID.set(inbound_message_id)
    try:
        graph_result = await support_graph.ainvoke({"params": {**params.model_dump(), "message_id": inbound_message_id}})
    except Exception as exc:
        return error_response(request_id, -32000, "Support agent failed", str(exc))
    finally:
        CURRENT_MESSAGE_ID.reset(message_token)
        CURRENT_TASK_ID.reset(task_token)
        CURRENT_CONTEXT_ID.reset(context_token)
    result = graph_result["result"]
    return success_response(request_id, result)


async def execute_support_task(*, task_id: str, params: dict[str, Any]) -> None:
    context_token = CURRENT_CONTEXT_ID.set(params["context_id"])
    task_token = CURRENT_TASK_ID.set(task_id)
    message_token = CURRENT_MESSAGE_ID.set(params.get("message_id"))
    try:
        await TASK_STORE.mark_working(task_id, stage="agent execution started")
        graph_result = await support_graph.ainvoke({"params": params})
        await TASK_STORE.complete(task_id, payload=graph_result["result"], run_id=params.get("run_id"))
    except Exception as exc:
        await TASK_STORE.fail(task_id, str(exc))
    finally:
        CURRENT_MESSAGE_ID.reset(message_token)
        CURRENT_TASK_ID.reset(task_token)
        CURRENT_CONTEXT_ID.reset(context_token)
