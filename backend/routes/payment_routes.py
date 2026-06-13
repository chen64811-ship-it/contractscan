"""
Lemon Squeezy payment webhook handler.
Receives order.created events, auto-generates unlock codes, stores them.
"""
import os
import hmac
import hashlib
import json
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/api/payment")

# In-memory code store: code -> {created_at, email, variant_name}
# Survives restarts? No. For production, use SQLite/Postgres.
_CODE_STORE: dict[str, dict] = {}
_CODE_TTL = 604800  # 7 days

# Load webhook secret
_WEBHOOK_SECRET = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "")

# File-based persistence fallback
_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "outputs" / ".codes.json"


def _generate_code() -> str:
    """Generate a human-readable unlock code like XKCD style."""
    return secrets.token_hex(4).upper()  # e.g. "A3F8B2C1"


def _save_store():
    """Persist codes to disk."""
    try:
        data = {
            k: {**v, "created_at": v["created_at"]}
            for k, v in _CODE_STORE.items()
        }
        _STORE_PATH.write_text(json.dumps(data))
    except Exception:
        pass


def _load_store():
    """Load persisted codes from disk."""
    if _STORE_PATH.exists():
        try:
            data = json.loads(_STORE_PATH.read_text())
            for k, v in data.items():
                _CODE_STORE[k] = v
        except Exception:
            pass


# Load on startup
_load_store()


def _verify_signature(body: bytes, signature: str) -> bool:
    """Verify Lemon Squeezy webhook signature."""
    if not _WEBHOOK_SECRET:
        return True  # No secret configured — skip verification (dev mode)
    expected = hmac.new(
        _WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def lemon_squeezy_webhook(request: Request):
    """
    Receive order.created events from Lemon Squeezy.
    Auto-generates an unlock code and stores it.
    """
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_signature(body, signature):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body")

    event_name = payload.get("meta", {}).get("event_name", "")
    if event_name != "order_created":
        return {"status": "ignored", "event": event_name}

    data = payload.get("data", {})
    attrs = data.get("attributes", {})
    email = attrs.get("user_email", "unknown")
    variant_name = attrs.get("variant_name", attrs.get("product_name", "Unknown Product"))
    order_id = str(data.get("id", "unknown"))

    # Check if this order already has a code
    for code, info in _CODE_STORE.items():
        if info.get("order_id") == order_id:
            return {"status": "duplicate", "code": code}

    # Generate unlock code
    code = _generate_code()
    _CODE_STORE[code] = {
        "created_at": time.time(),
        "email": email,
        "variant_name": variant_name,
        "order_id": order_id,
    }
    _save_store()

    print(f"[Payment] New unlock code: {code} for {email} ({variant_name})")

    return {
        "status": "ok",
        "code": code,
        "email": email,
        "product": variant_name,
    }


@router.get("/codes")
async def list_codes(key: str = ""):
    """
    List all active unlock codes. Requires admin key (ADMIN_KEY env var).
    """
    admin_key = os.getenv("ADMIN_KEY", "")
    if not admin_key or key != admin_key:
        raise HTTPException(403, "Invalid admin key")
    
    now = time.time()
    active = []
    for code, info in _CODE_STORE.items():
        age_hours = (now - info["created_at"]) / 3600
        active.append({
            "code": code,
            "email": info["email"],
            "product": info["variant_name"],
            "age_hours": round(age_hours, 1),
        })
    return {"codes": sorted(active, key=lambda x: x["age_hours"])}


@router.get("/success")
async def payment_success(email: str = ""):
    """
    Payment success redirect page.
    Looks up unlock code by email and shows it.
    Set this as Lemon Squeezy checkout success URL:
      https://your-domain.com/api/payment/success?email={email}
    """
    if not email:
        return {"status": "ok", "message": "Payment received! Check your email for the unlock code."}
    
    # Find most recent code for this email
    now = time.time()
    best_code = None
    for code, info in _CODE_STORE.items():
        if info.get("email", "").lower() == email.lower():
            if now - info["created_at"] < _CODE_TTL:
                if best_code is None or info["created_at"] > _CODE_STORE[best_code]["created_at"]:
                    best_code = code
    
    if best_code:
        return {
            "status": "ok",
            "code": best_code,
        }
    
    return {
        "status": "pending",
        "message": "Payment confirmed. Your unlock code will appear here shortly. Refresh in a few seconds."
    }
