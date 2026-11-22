"""Inventory API - simulates product reservation. Fault scenario 1: latency injection."""
import asyncio
import random

from services.telemetry import apply_faults, busy_work, create_service

app, faults, tracer = create_service("inventory")


@app.post("/reserve")
async def reserve(order: dict):
    with tracer.start_as_current_span("inventory.reserve_stock") as span:
        span.set_attribute("order.item", order.get("item", "unknown"))
        span.set_attribute("order.qty", order.get("qty", 1))
        busy_work(random.uniform(0.5, 2.0))
        await asyncio.sleep(random.uniform(0.02, 0.05))  # simulated DB lookup
        err = await apply_faults(faults, span)
        if err:
            return err
        return {"reserved": True, "item": order.get("item"), "qty": order.get("qty", 1)}
