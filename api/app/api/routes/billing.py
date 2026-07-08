"""Stripe billing (PLAN.md §5's credit/subscription framework). Checkout is
the only path a browser talks to directly; the webhook is what actually
flips a user's tier — a client-side "checkout completed" redirect is never
trusted on its own, only the server-to-server webhook is.

No live Stripe account exists for this deployment: both routes detect a
missing STRIPE_SECRET_KEY/STRIPE_WEBHOOK_SECRET and return 503 rather than
crash, the same "wired but inactive until configured" pattern as Tier-1
platform APIs (§12)."""

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.users import current_active_user
from app.db.session import get_db
from shared.models import User
from shared.models.enums import UserRole

router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger(__name__)


@router.post("/checkout")
async def create_checkout_session(user: User = Depends(current_active_user)) -> dict:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured on this deployment.")
    if not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="No price configured for the paid tier.")

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        customer=user.stripe_customer_id or None,
        customer_email=user.email if not user.stripe_customer_id else None,
        client_reference_id=str(user.id),
        success_url=f"{settings.public_web_url}/account?checkout=success",
        cancel_url=f"{settings.public_web_url}/pricing?checkout=cancelled",
    )
    return {"checkout_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Billing is not configured on this deployment.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    event_type = event["type"]
    # stripe.Webhook.construct_event returns a StripeObject, not a plain
    # dict — it supports attribute/bracket access but not .get(), which
    # raises AttributeError rather than returning None for a missing key.
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id = getattr(data, "client_reference_id", None)
        customer_id = getattr(data, "customer", None)
        if user_id:
            user = await db.get(User, user_id)
            if user is not None:
                user.role = UserRole.PAID
                if customer_id:
                    user.stripe_customer_id = customer_id
                await db.commit()
                logger.info("user %s upgraded to paid via checkout", user_id)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        customer_id = getattr(data, "customer", None)
        sub_status = getattr(data, "status", None)
        if customer_id and (event_type == "customer.subscription.deleted" or sub_status in ("canceled", "unpaid", "incomplete_expired")):
            result = await db.execute(select(User).filter(User.stripe_customer_id == customer_id))
            user = result.scalar_one_or_none()
            if user is not None:
                user.role = UserRole.FREE
                await db.commit()
                logger.info("user %s downgraded to free (subscription %s)", user.id, sub_status)

    return {"received": True}
