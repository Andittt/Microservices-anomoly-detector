"""Payment API - simulates payment processing. Fault scenario 2: error-rate injection."""
import asyncio
import random

from fastapi.responses import JSONResponse

from services.telemetry import apply_faults, busy_work, create_service

app, faults, tracer = create_service("payment")


@app.post("/charge")
async def charge(payment: dict):
    with tracer.start_as_current_span("payment.charge_card") as span:
        span.set_attribute("payment.amount", payment.get("amount", 0))
        busy_work(random.uniform(0.5, 2.0))
        await asyncio.sleep(random.uniform(0.03, 0.07))  # simulated gateway call
        err = await apply_faults(faults, span)
        if err:
            return err
        # ~2% of cards are declined: a normal business outcome (4xx), not a server error
        if random.random() < 0.02:
            return JSONResponse({"charged": False, "reason": "card_declined"}, status_code=402)
        return {"charged": True, "amount": payment.get("amount", 0)}
