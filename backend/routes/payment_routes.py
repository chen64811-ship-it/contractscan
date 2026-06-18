"""Lemon Squeezy payment webhook handler.
Receives order.created events, auto-generates unlock codes, stores them in MySQL via SQLAlchemy.
"""
import os
import hmac
import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from db import get_db
from models import UnlockCode, Order

router = APIRouter(prefix="/api/payment")

# TTL for codes (seconds)
_CODE_TTL = 604800  # 7 days

# Load webhook secret
_WEBHOOK_SECRET = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "")


def _generate_code() -> str:
    """Generate a short unlock code."""
    return secrets.token_hex(4).upper()


def _verify_signature(body: bytes, signature: str) -> bool:
    """Verify Lemon Squeezy webhook signature."""
    if not _WEBHOOK_SECRET:
        return True
    expected = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def lemon_squeezy_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle webhook, create Order and UnlockCode records."""
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_signature(body, signature):
        raise HTTPException(401, "Invalid webhook signature")

    payload = None
    try:
        payload = await request.json()
    except Exception:
        # Try robust JSON parsing from body bytes
        try:
            import json as _json
            payload = _json.loads(body)
        except Exception:
            raise HTTPException(400, "Invalid JSON body")

    event_name = payload.get("meta", {}).get("event_name", "")
    if event_name != "order_created":
        return {"status": "ignored", "event": event_name}

    data = payload.get("data", {})
    attrs = data.get("attributes", {})
    email = attrs.get("user_email", "unknown")
    variant_name = attrs.get("variant_name", attrs.get("product_name", "Unknown Product"))
    order_id = str(data.get("id", "unknown"))

    # If an unlock code already exists for this order, return it
    existing = db.query(UnlockCode).filter(UnlockCode.order_id == order_id).first()
    if existing:
        return {"status": "duplicate", "code": existing.code}

    # Create order record if not exists
    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order:
        order = Order(order_id=order_id, email=email, variant_name=variant_name)
        db.add(order)

    # Create unlock code
    code = _generate_code()
    unlock = UnlockCode(code=code, created_at=datetime.utcnow(), email=email, order_id=order_id, is_multi_use=False)
    db.add(unlock)
    db.commit()

    print(f"[Payment] New unlock code: {code} for {email} ({variant_name})")

    return {"status": "ok", "code": code, "email": email, "product": variant_name}


@router.get("/codes")
async def list_codes(key: str = "", db: Session = Depends(get_db)):
    """Admin: list active unlock codes."""
    admin_key = os.getenv("ADMIN_KEY", "")
    if not admin_key or key != admin_key:
        raise HTTPException(403, "Invalid admin key")

    now = datetime.utcnow()
    codes = db.query(UnlockCode).all()
    active = []
    for c in codes:
        age_hours = (now - c.created_at).total_seconds() / 3600
        # Look up product via Order if available
        product = None
        if c.order_id:
            ord_row = db.query(Order).filter(Order.order_id == c.order_id).first()
            product = ord_row.variant_name if ord_row else None
        active.append({
            "code": c.code,
            "email": c.email,
            "product": product,
            "age_hours": round(age_hours, 1),
        })

    return {"codes": sorted(active, key=lambda x: x["age_hours"]) }


@router.get("/success")
async def payment_success(email: str = "", db: Session = Depends(get_db)):
    """Lookup most recent unlock code by email."""
    if not email:
        return {"status": "ok", "message": "Payment received! Check your email for the unlock code."}

    # Case-insensitive lookup
    code_row = db.query(UnlockCode).filter(func.lower(UnlockCode.email) == email.lower()).order_by(UnlockCode.created_at.desc()).first()

    if code_row and (datetime.utcnow() - code_row.created_at).total_seconds() < _CODE_TTL:
        return {"status": "ok", "code": code_row.code}

    return {"status": "pending", "message": "Payment confirmed. Your unlock code will appear here shortly. Refresh in a few seconds."}

