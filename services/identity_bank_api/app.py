from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import BaseModel, Field
from fastapi import FastAPI, Header, HTTPException


app = FastAPI(title="Delegated banking MCP API", version="1.0.0")


class PaymentRequest(BaseModel):
    customer_id: str
    amount_usd: float = Field(gt=0)


def decoded_access_token(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A delegated MCP access token is required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Unable to read delegated access token") from exc


def token_evidence(claims: dict[str, Any]) -> dict[str, Any]:
    """Return presentation-safe claims only; never return a bearer token."""
    return {
        "issuer": claims.get("iss"),
        "human_subject": claims.get("human_subject") or claims.get("preferred_username") or claims.get("sub"),
        "human_display_name": claims.get("name"),
        "actor": claims.get("act") or claims.get("acting_agent") or claims.get("azp"),
        "audience": claims.get("aud"),
        "delegated_tool_scopes": claims.get("delegated_tool_scopes"),
        "delegated_customer_id": claims.get("delegated_customer_id"),
        "expires_at": claims.get("exp"),
        "token_id": claims.get("jti"),
    }


@app.get("/portfolio/{customer_id}")
async def get_customer_portfolio(customer_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    claims = decoded_access_token(authorization)
    delegated_customer_id = claims.get("delegated_customer_id")
    if delegated_customer_id != customer_id:
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "The downscoped token is not delegated for this customer.",
                "requested_customer_id": customer_id,
                "delegated_customer_id": delegated_customer_id,
            },
        )

    return {
        "customer_id": customer_id,
        "customer_name": "Acme Health",
        "portfolio_summary": "Strategic enterprise account with a managed renewal plan.",
        "token_evidence": token_evidence(claims),
    }


@app.post("/payments/initiate")
async def initiate_payment(payload: PaymentRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    claims = decoded_access_token(authorization)
    delegated_customer_id = claims.get("delegated_customer_id")
    if delegated_customer_id != payload.customer_id:
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "The downscoped token is not delegated for this customer.",
                "requested_customer_id": payload.customer_id,
                "delegated_customer_id": delegated_customer_id,
            },
        )

    return {
        "payment_id": "PAY-DEMO-1042",
        "status": "accepted",
        "customer_id": payload.customer_id,
        "amount_usd": payload.amount_usd,
        "token_evidence": token_evidence(claims),
    }
