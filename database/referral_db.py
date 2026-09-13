from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_NAME
from .admin_settings_db import get_setting
from .users_chats_db import db as user_db

client = AsyncIOMotorClient(DATABASE_URI)
db = client["admin_database"]
relations = db["referral_relations"]
ledger = db["referral_ledger"]
activations = db["referral_activations"]

async def ensure_indexes():
    await relations.create_index([("invitee_id", 1)], unique=True, name="uniq_invitee")
    await ledger.create_index([("event_id", 1)], unique=True, sparse=True, name="uniq_event")
    await ledger.create_index([("user_id", 1), ("created_at", -1)])
    await activations.create_index([("invitee_id", 1)], unique=True, name="uniq_activation_invitee")

async def register_referral(inviter_id, invitee_id):
    inviter_id, invitee_id = int(inviter_id), int(invitee_id)
    if inviter_id == invitee_id:
        return False, "self"
    existing = await relations.find_one({"invitee_id": invitee_id})
    if existing:
        return False, "already"
    try:
        await relations.insert_one({"inviter_id": inviter_id, "invitee_id": invitee_id, "status": "pending", "created_at": datetime.now(timezone.utc)})
        return True, "created"
    except Exception:
        return False, "already"

async def qualify_referral(invitee_id, reason="first_successful_search"):
    invitee_id = int(invitee_id)
    rel = await relations.find_one({"invitee_id": invitee_id, "status": "pending"})
    if not rel:
        return None
    now = datetime.now(timezone.utc)
    points = int(await get_setting("referral_reward_points", 5))
    result = await relations.update_one({"_id": rel["_id"], "status": "pending"}, {"$set": {"status": "qualified", "qualified_at": now, "qualification_reason": reason}})
    if result.modified_count != 1:
        return None
    await activations.insert_one({"invitee_id": invitee_id, "inviter_id": rel["inviter_id"], "points": points, "reason": reason, "created_at": now})
    event_id = f"referral:{invitee_id}"
    try:
        await ledger.insert_one({"event_id": event_id, "user_id": rel["inviter_id"], "invitee_id": invitee_id, "type": "earned", "points": points, "created_at": now})
    except Exception:
        return None
    await user_db.users.update_one({"id": rel["inviter_id"]}, {"$inc": {"referral_points": points, "referral_total_earned": points}, "$set": {"referral_updated_at": now}}, upsert=False)
    return {"inviter_id": rel["inviter_id"], "invitee_id": invitee_id, "points": points}

async def get_dashboard(user_id):
    user_id = int(user_id)
    u = await user_db.users.find_one({"id": user_id}) or {}
    qualified = await relations.count_documents({"inviter_id": user_id, "status": "qualified"})
    pending = await relations.count_documents({"inviter_id": user_id, "status": "pending"})
    return {"points": int(u.get("referral_points", 0) or 0), "earned": int(u.get("referral_total_earned", 0) or 0), "qualified": qualified, "pending": pending}

async def history(user_id, limit=20):
    return await relations.find({"inviter_id": int(user_id)}).sort("created_at", -1).to_list(length=limit)

async def activation_history(user_id, limit=20):
    return await activations.find({"inviter_id": int(user_id)}).sort("created_at", -1).to_list(length=limit)

async def redeem_points(user_id):
    user_id = int(user_id)
    threshold = int(await get_setting("referral_redeem_points", 20))
    days = int(await get_setting("referral_redeem_days", 10))
    u = await user_db.users.find_one({"id": user_id})
    if not u:
        return False, 0, 0
    points = int(u.get("referral_points", 0) or 0)
    if points < threshold:
        return False, points, 0
    bundles = points // threshold
    used = bundles * threshold
    # Atomic deduction prevents double-click redeems from overspending points.
    result = await user_db.users.update_one({"id": user_id, "referral_points": {"$gte": used}}, {"$inc": {"referral_points": -used}})
    if result.modified_count != 1:
        return False, points, 0
    await ledger.insert_one({"user_id": user_id, "type": "redeemed", "points": -used, "days": bundles * days, "created_at": datetime.now(timezone.utc)})
    return True, points - used, bundles * days
