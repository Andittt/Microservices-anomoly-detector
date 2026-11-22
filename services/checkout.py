"""Checkout API - entry point. Calls inventory then payment; its response reflects downstream outcomes."""
import random

import httpx
from fastapi.responses import JSONResponse
from opentelemetry.trace import StatusCode

from common import config
from services.telemetry import busy_work, create_service

app, faults, tracer = create_service("checkout")
client = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(keepalive_expiry=2.0))  # < uvicorn 5 s idle timeout

ITEMS = ["keyboard", "mouse", "monitor", "headset", "webcam", "laptop-stand"]


@app.post("/checkout")
async def checkout(order: dict | None = None):
    order = order or {}
    item = order.get("item", random.choice(ITEMS))
    qty = int(order.get("qty", random.randint(1, 3)))
    with tracer.start_as_current_span("checkout.process_order") as span:
        span.set_attribute("order.item", item)
        busy_work(random.uniform(0.3, 1.0))

        try:
            inv = await client.post(f"{config.INVENTORY_URL}/reserve", json={"item": item, "qty": qty})
        except httpx.HTTPError as e:
            span.set_status(StatusCode.ERROR, "inventory unreachable")
            return JSONResponse({"ok": False, "stage": "inventory", "error": str(e)}, status_code=502)
        if inv.status_code >= 500:
            span.set_status(StatusCode.ERROR, "inventory failed")
            return JSONResponse({"ok": False, "stage": "inventory"}, status_code=502)

        try:
            pay = await client.post(f"{config.PAYMENT_URL}/charge", json={"amount": qty * 49.99})
        except httpx.HTTPError as e:
            span.set_status(StatusCode.ERROR, "payment unreachable")
            return JSONResponse({"ok": False, "stage": "payment", "error": str(e)}, status_code=502)
        if pay.status_code >= 500:
            span.set_status(StatusCode.ERROR, "payment failed")
            return JSONResponse({"ok": False, "stage": "payment"}, status_code=502)
        if pay.status_code == 402:
            return JSONResponse({"ok": False, "stage": "payment", "reason": "card_declined"}, status_code=402)

        return {"ok": True, "item": item, "qty": qty}
