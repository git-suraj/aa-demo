from __future__ import annotations

import json
import os
from typing import Any

import httpx

from services.common.trace_context import current_trace_headers


class OrchestratorLLM:
    def __init__(self) -> None:
        self.kong_api_key = os.getenv("AGENT_API_KEY")
        self.base_url = (
            os.getenv("KONG_AI_PROXY_URL")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
        )
        self.model = os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL") or "gpt-4.1-mini"

    @property
    def enabled(self) -> bool:
        return bool(self.kong_api_key and self.base_url)

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        base_url: str | None = None,
        model: str | None = None,
        run_id: str | None = None,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
        scenario_mode: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Kong-routed LLM is not configured")

        resolved_base_url = (base_url or self.base_url or "").rstrip("/")
        resolved_model = model or self.model
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{resolved_base_url}/chat/completions",
                headers={
                    "apikey": self.kong_api_key or "",
                    "content-type": "application/json",
                    **current_trace_headers(),
                    **({"x-demo-run-id": run_id} if run_id else {}),
                    **({"x-demo-context-id": context_id} if context_id else {}),
                    **({"x-demo-task-id": task_id} if task_id else {}),
                    **({"x-demo-message-id": message_id} if message_id else {}),
                    **({"x-demo-scenario-mode": scenario_mode} if scenario_mode else {}),
                },
                json={
                    "model": resolved_model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = payload.get("choices", [{}])[0].get("message", {}).get("content") or ""
        return {
            "llm_used": True,
            "model": resolved_model,
            "summary": text.strip(),
        }

    async def generate_with_headers(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        base_url: str | None = None,
        model: str | None = None,
        run_id: str | None = None,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
        scenario_mode: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Kong-routed LLM is not configured")

        resolved_base_url = (base_url or self.base_url or "").rstrip("/")
        resolved_model = model or self.model
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{resolved_base_url}/chat/completions",
                headers={
                    "apikey": self.kong_api_key or "",
                    "content-type": "application/json",
                    **current_trace_headers(),
                    **({"x-demo-run-id": run_id} if run_id else {}),
                    **({"x-demo-context-id": context_id} if context_id else {}),
                    **({"x-demo-task-id": task_id} if task_id else {}),
                    **({"x-demo-message-id": message_id} if message_id else {}),
                    **({"x-demo-scenario-mode": scenario_mode} if scenario_mode else {}),
                },
                json={
                    "model": resolved_model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = payload.get("choices", [{}])[0].get("message", {}).get("content") or ""
        cache_headers = {
            "x-cache-status": response.headers.get("x-cache-status"),
            "x-cache-key": response.headers.get("x-cache-key"),
            "x-cache-ttl": response.headers.get("x-cache-ttl"),
            "age": response.headers.get("age"),
        }
        return {
            "llm_used": True,
            "model": resolved_model,
            "summary": text.strip(),
            "cache_headers": cache_headers,
        }

    async def summarize_escalation(
        self,
        *,
        account_name: str,
        issue_summary: str,
        renewal_risk: Any,
        open_tickets: Any,
        support_track: Any | None = None,
        success_track: Any | None = None,
        run_id: str | None = None,
        context_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return self._fallback(
                account_name=account_name,
                issue_summary=issue_summary,
                renewal_risk=renewal_risk,
                open_tickets=open_tickets,
                support_track=support_track,
                success_track=success_track,
            )

        prompts = self.build_executive_prompts(
            account_name=account_name,
            issue_summary=issue_summary,
            renewal_risk=renewal_risk,
            open_tickets=open_tickets,
            support_track=support_track,
            success_track=success_track,
        )
        return await self.generate(**prompts, run_id=run_id, context_id=context_id)

    def build_executive_prompts(
        self,
        *,
        account_name: str,
        issue_summary: str,
        renewal_risk: Any,
        open_tickets: Any,
        support_track: Any | None = None,
        success_track: Any | None = None,
    ) -> dict[str, str]:
        renewal_summary = self._summarize_renewal_risk(renewal_risk)
        ticket_summary = self._summarize_open_tickets(open_tickets)
        support_summary = self._summarize_support_track(support_track)
        success_summary = self._summarize_success_track(success_track)
        return {
            "system_prompt": (
                "You are an orchestrator preparing an executive escalation brief. "
                "Be concise, concrete, and business-oriented."
            ),
            "user_prompt": (
                "Write a concise response with three sections:\n"
                "1. Situation\n"
                "2. Recommended next actions\n"
                "3. Customer communication posture\n\n"
                f"Account: {account_name}\n"
                f"Issue summary: {issue_summary}\n"
                f"Renewal risk: {renewal_summary}\n"
                f"Open tickets: {ticket_summary}\n"
                f"Support track: {support_summary}\n"
                f"Success track: {success_summary}\n"
            ),
        }

    async def choose_tools(
        self,
        *,
        account_name: str,
        issue_summary: str,
        product_issue: str,
        billing_issue: str,
        available_tools: list[str],
        run_id: str | None = None,
        context_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            selected_tools = [
                tool
                for tool in available_tools
                if tool in {"get_customer_account", "get_renewal_risk", "get_open_tickets"}
            ]
            return {
                "llm_used": False,
                "model": None,
                "selected_tools": selected_tools,
                "reasoning": "Fallback planner selected the standard customer context tools for this escalation.",
            }

        prompts = self.build_tool_selection_prompts(
            account_name=account_name,
            issue_summary=issue_summary,
            product_issue=product_issue,
            billing_issue=billing_issue,
            available_tools=available_tools,
        )
        response = await self.generate(**prompts, run_id=run_id, context_id=context_id)
        selected_tools = list(available_tools)
        reasoning = response["summary"]

        try:
            parsed = json.loads(response["summary"])
            tool_candidates = parsed.get("selected_tools", [])
            selected_tools = [tool for tool in tool_candidates if tool in available_tools] or list(available_tools)
            reasoning = parsed.get("reasoning", reasoning)
        except json.JSONDecodeError:
            pass

        return {
            "llm_used": response["llm_used"],
            "model": response["model"],
            "selected_tools": selected_tools,
            "reasoning": reasoning,
        }

    def build_tool_selection_prompts(
        self,
        *,
        account_name: str,
        issue_summary: str,
        product_issue: str,
        billing_issue: str,
        available_tools: list[str],
    ) -> dict[str, str]:
        return {
            "system_prompt": (
                "You are an orchestration planner. "
                "Choose only the MCP tools that are needed to build initial context for the escalation. "
                "Return strict JSON with keys selected_tools and reasoning."
            ),
            "user_prompt": (
                f"Account: {account_name}\n"
                f"Issue summary: {issue_summary}\n"
                f"Product issue: {product_issue}\n"
                f"Billing issue: {billing_issue}\n"
                f"Available tools: {available_tools}\n\n"
                "Return JSON like:\n"
                "{\"selected_tools\": [\"tool_name\"], \"reasoning\": \"short explanation\"}"
            ),
        }

    async def choose_next_tool(
        self,
        *,
        account_name: str,
        issue_summary: str,
        product_issue: str,
        billing_issue: str,
        available_tools: list[str],
        remaining_tools: list[str],
        current_context: dict[str, Any],
        run_id: str | None = None,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        if not remaining_tools:
            return {
                "llm_used": False,
                "model": None,
                "done": True,
                "next_tool": None,
                "arguments": {},
                "reasoning": "No remaining tools to plan.",
            }

        if not self.enabled:
            tool_priority = [
                "get_customer_account",
                "get_renewal_risk",
                "get_open_tickets",
            ]
            next_tool = next((tool for tool in tool_priority if tool in remaining_tools), remaining_tools[0])
            return {
                "llm_used": False,
                "model": None,
                "done": False,
                "next_tool": next_tool,
                "arguments": {},
                "reasoning": f"Fallback planner selected {next_tool} as the next required customer-context tool.",
            }

        prompts = self.build_next_tool_prompts(
            account_name=account_name,
            issue_summary=issue_summary,
            product_issue=product_issue,
            billing_issue=billing_issue,
            available_tools=available_tools,
            remaining_tools=remaining_tools,
            current_context=current_context,
        )
        response = await self.generate(
            **prompts,
            run_id=run_id,
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
        )
        decision = {
            "llm_used": response["llm_used"],
            "model": response["model"],
            "done": False,
            "next_tool": remaining_tools[0],
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

    def build_next_tool_prompts(
        self,
        *,
        account_name: str,
        issue_summary: str,
        product_issue: str,
        billing_issue: str,
        available_tools: list[str],
        remaining_tools: list[str],
        current_context: dict[str, Any],
    ) -> dict[str, str]:
        return {
            "system_prompt": (
                "You are the orchestrator planning one MCP tool call at a time. "
                "Inspect the current context, choose the single best next tool, and propose its arguments. "
                "Return strict JSON with keys done, next_tool, arguments, and reasoning. "
                "If enough context has been gathered, return done=true and next_tool=null."
            ),
            "user_prompt": (
                f"Account: {account_name}\n"
                f"Issue summary: {issue_summary}\n"
                f"Product issue: {product_issue}\n"
                f"Billing issue: {billing_issue}\n"
                f"Available tools: {available_tools}\n"
                f"Remaining tools: {remaining_tools}\n"
                f"Current context: {json.dumps(current_context, ensure_ascii=True)}\n\n"
                "For customer lookup tools, arguments may use customer_id.\n"
                "Return JSON like:\n"
                "{\"done\": false, \"next_tool\": \"get_customer_account\", \"arguments\": {\"customer_id\": \"cust_acme\"}, \"reasoning\": \"Need the account record first.\"}"
            ),
        }

    def _fallback(
        self,
        *,
        account_name: str,
        issue_summary: str,
        renewal_risk: Any,
        open_tickets: Any,
        support_track: Any | None = None,
        success_track: Any | None = None,
    ) -> dict[str, Any]:
        response = (
            f"Situation: {account_name} has an active escalation tied to {issue_summary}. "
            f"Renewal risk is {renewal_risk}. Open tickets: {open_tickets}. "
            f"Recommended next actions: stabilize the technical issue, resolve the billing concern, "
            "and maintain named ownership across support and success. "
            f"Customer communication posture: communicate the technical plan ({support_track}) and "
            f"the customer follow-up plan ({success_track}) with a same-day executive update."
        )
        return {
            "llm_used": False,
            "model": None,
            "summary": response,
        }

    def _coerce_json_payload(self, value: Any) -> Any:
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) and value[0].get("type") == "text":
            text = value[0].get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        if isinstance(value, dict) and value.get("type") == "text" and isinstance(value.get("text"), str):
            try:
                return json.loads(value["text"])
            except json.JSONDecodeError:
                return value["text"]
        return value

    def _summarize_renewal_risk(self, renewal_risk: Any) -> str:
        payload = self._coerce_json_payload(renewal_risk)
        if isinstance(payload, dict):
            drivers = ", ".join(payload.get("drivers", [])[:3])
            return f"score={payload.get('score')}, level={payload.get('level')}, drivers={drivers}"
        return str(payload)

    def _summarize_open_tickets(self, open_tickets: Any) -> str:
        payload = self._coerce_json_payload(open_tickets)
        if isinstance(payload, dict):
            tickets = payload.get("tickets", [])[:3]
            parts = [
                f"{ticket.get('ticket_id')} ({ticket.get('severity')}): {ticket.get('summary')}"
                for ticket in tickets
            ]
            return "; ".join(parts)
        return str(payload)

    def _summarize_support_track(self, support_track: Any) -> str:
        payload = self._coerce_json_payload(support_track)
        if isinstance(payload, dict):
            actions = ", ".join((payload.get("recommended_actions") or [])[:3])
            return (
                f"technical_response={payload.get('technical_response')}; "
                f"recommended_actions={actions}"
            )
        return str(payload)

    def _summarize_success_track(self, success_track: Any) -> str:
        payload = self._coerce_json_payload(success_track)
        if isinstance(payload, dict):
            plan = ", ".join((payload.get("success_plan") or [])[:3])
            llm_summary = (payload.get("llm_summary") or {}).get("summary")
            return f"success_plan={plan}; communication_summary={llm_summary}"
        return str(payload)
