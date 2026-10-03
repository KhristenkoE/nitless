"""Client for the external payment gateway."""

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class GatewayResult:
    approved: bool
    reference: str | None
    decline_reason: str | None = None


class PaymentGateway:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=settings.payment_gateway_url,
            timeout=settings.payment_gateway_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.payment_gateway_api_key.get_secret_value()}"},
        )

    def charge(self, *, amount_cents: int, currency: str, payment_token: str, idempotency_key: str) -> GatewayResult:
        body = {"amount": amount_cents, "currency": currency, "source": payment_token}
        data = self._post("/v1/charges", body, idempotency_key)
        return GatewayResult(
            approved=data["status"] == "succeeded",
            reference=data.get("id"),
            decline_reason=data.get("decline_code"),
        )

    def refund(self, *, provider_ref: str, amount_cents: int, idempotency_key: str) -> GatewayResult:
        data = self._post("/v1/refunds", {"charge": provider_ref, "amount": amount_cents}, idempotency_key)
        return GatewayResult(approved=data["status"] == "succeeded", reference=data.get("id"))

    def _post(self, path: str, body: dict[str, object], idempotency_key: str) -> dict[str, str]:
        try:
            response = self._client.post(path, json=body, headers={"Idempotency-Key": idempotency_key})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("payment_gateway_error", path=path, error=str(exc))
            raise UpstreamError("payment gateway unavailable") from exc
        return response.json()
