from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part, TaskState, TextPart
from fastapi import FastAPI, Request
from pydantic import BaseModel

from services.common.trace_context import reset_trace_headers
from services.common.trace_context import set_trace_headers_from_request


class GraphAgentExecutor(AgentExecutor):
    def __init__(
        self,
        *,
        agent_id: str,
        graph: Any,
        params_model: type[BaseModel],
        context_var: ContextVar[str | None],
        task_var: ContextVar[str | None],
        message_var: ContextVar[str | None],
    ) -> None:
        self.agent_id = agent_id
        self.graph = graph
        self.params_model = params_model
        self.context_var = context_var
        self.task_var = task_var
        self.message_var = message_var

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or ""
        context_id = context.context_id or ""
        message_id = context.message.message_id if context.message else None
        updater = TaskUpdater(event_queue, task_id, context_id)

        context_token = self.context_var.set(context_id)
        task_token = self.task_var.set(task_id)
        message_token = self.message_var.set(message_id)
        try:
            params = self.params_model.model_validate(json.loads(context.get_user_input()))
            params_payload = {
                **params.model_dump(),
                "task_id": task_id,
                "message_id": message_id,
            }
            await updater.submit()
            await updater.start_work()
            graph_result = await self.graph.ainvoke({"params": params_payload})
            result = graph_result["result"]
            result_text = json.dumps(result, ensure_ascii=False)
            parts = [Part(root=TextPart(text=result_text))]
            await updater.add_artifact(
                parts,
                artifact_id=f"{self.agent_id}-result",
                name=f"{self.agent_id} result",
                metadata={"agent_id": self.agent_id, "run_id": params_payload.get("run_id")},
                last_chunk=True,
            )
            await updater.complete(
                updater.new_agent_message(parts, metadata={"agent_id": self.agent_id, "run_id": params_payload.get("run_id")})
            )
        except Exception as exc:
            message = updater.new_agent_message([Part(root=TextPart(text=str(exc)))], metadata={"agent_id": self.agent_id})
            await updater.update_status(TaskState.failed, message=message, final=True, metadata={"agent_id": self.agent_id})
        finally:
            self.message_var.reset(message_token)
            self.task_var.reset(task_token)
            self.context_var.reset(context_token)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")
        await updater.cancel(updater.new_agent_message([Part(root=TextPart(text="Task canceled"))]))


def build_agent_card(
    *,
    agent_id: str,
    name: str,
    description: str,
    url: str,
    skill_id: str,
    skill_name: str,
    skill_description: str,
) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        url=url,
        version="1.0.0",
        preferredTransport="JSONRPC",
        additionalInterfaces=[
            AgentInterface(transport="JSONRPC", url=url),
            AgentInterface(transport="A2A", url=url),
        ],
        capabilities=AgentCapabilities(streaming=True, stateTransitionHistory=True),
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_name,
                description=skill_description,
                tags=[agent_id, "customer-escalation"],
                inputModes=["application/json", "text/plain"],
                outputModes=["application/json", "text/plain"],
            )
        ],
    )


def add_trace_context_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_context_middleware(request: Request, call_next):
        token = set_trace_headers_from_request(request)
        try:
            return await call_next(request)
        finally:
            reset_trace_headers(token)


def add_a2a_sdk_routes(
    *,
    app: FastAPI,
    agent_card: AgentCard,
    executor: AgentExecutor,
    route_prefix: str,
) -> None:
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    a2a_app = A2AFastAPIApplication(agent_card=agent_card, http_handler=handler)
    a2a_app.add_routes_to_app(app, agent_card_url="/.well-known/agent-card.json", rpc_url="/a2a")
    a2a_app.add_routes_to_app(app, agent_card_url=f"{route_prefix}/.well-known/agent-card.json", rpc_url=f"{route_prefix}/a2a")
    a2a_app.add_routes_to_app(app, agent_card_url=f"{route_prefix}/.well-known/agent.json", rpc_url=f"{route_prefix}/v1/jsonrpc")
