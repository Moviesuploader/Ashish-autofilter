import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI

client = AsyncIOMotorClient(DATABASE_URI)
db = client["admin_database"]
settings_col = db["bot_settings"]
logs_col = db["admin_activity_logs"]
index_col = db["index_state"]

DEFAULTS = {
    "maintenance_mode": False,
    "shortener_enabled": True,
    "content_forwarding_enabled": True,
    "pm_search_enabled": True,
    "movie_updates_enabled": True,
    "request_system_enabled": True,
    "streaming_enabled": True,
    "verification_enabled": True,
    "force_sub_enabled": True,
    "auto_delete_enabled": True,
    "auth_enabled": True,
    "backup_enabled": True,
    "logging_enabled": True,
    "referral_enabled": True,
    "payment_upi_enabled": True,
    "payment_crypto_enabled": True,
    "payment_stars_enabled": True,
    "request_channel": None,
    "movie_update_channel": None,
    "movie_update_channel_link": None,
    "backup_channel": None,
    "auth_channels": [],
    "log_channel": None,
    "premium_logs": None,
    "referral_reward_points": 5,
    "referral_redeem_points": 20,
    "referral_redeem_days": 10,
    "referral_qualification": "first_successful_search",
    "index_skip_default": 2,
    "premium_plans": {
        "bronze": {"enabled": True, "days": 7, "price": 10},
        "silver": {"enabled": True, "days": 15, "price": 20},
        "gold": {"enabled": True, "days": 30, "price": 40},
        "platinum": {"enabled": True, "days": 45, "price": 55},
        "diamond": {"enabled": True, "days": 60, "price": 75},
    },
}

async def ensure_settings():
    doc = await settings_col.find_one({"_id": "global"})
    if not doc:
        await settings_col.insert_one({"_id": "global", **DEFAULTS, "created_at": datetime.now(timezone.utc)})
    else:
        missing = {k: v for k, v in DEFAULTS.items() if k not in doc}
        if missing:
            await settings_col.update_one({"_id": "global"}, {"$set": missing})

async def get_setting(key, default=None):
    await ensure_settings()
    doc = await settings_col.find_one({"_id": "global"}, {key: 1})
    if doc and key in doc:
        return doc[key]
    if default is not None:
        return default
    return DEFAULTS.get(key)

async def set_setting(key, value, admin_id=None):
    await ensure_settings()
    await settings_col.update_one({"_id": "global"}, {"$set": {key: value, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    if admin_id:
        await logs_col.insert_one({"admin_id": int(admin_id), "action": "setting", "key": key, "value": value, "created_at": datetime.now(timezone.utc)})

async def get_all_settings():
    await ensure_settings()
    return await settings_col.find_one({"_id": "global"}) or {}

async def log_admin_action(admin_id, action, details=None):
    await logs_col.insert_one({"admin_id": int(admin_id), "action": action, "details": details or {}, "created_at": datetime.now(timezone.utc)})

async def get_index_skip(chat_id, default=None):
    doc = await index_col.find_one({"chat_id": str(chat_id)})
    if doc and "last_processed" in doc:
        return int(doc["last_processed"])
    return int(await get_setting("index_skip_default", default if default is not None else 2))

async def set_index_skip(chat_id, message_id):
    await index_col.update_one({"chat_id": str(chat_id)}, {"$set": {"chat_id": str(chat_id), "last_processed": int(message_id), "updated_at": datetime.now(timezone.utc)}}, upsert=True)

async def get_index_state(chat_id=None):
    if chat_id is None:
        return await index_col.find({}).sort("updated_at", -1).to_list(length=50)
    return await index_col.find_one({"chat_id": str(chat_id)})
