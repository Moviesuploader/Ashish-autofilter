import os, io, uuid, asyncio
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp
import qrcode
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from pymongo import ReturnDocument, ASCENDING
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

from info import ADMINS, OWNER_UPI_ID, QR_CODE, PREMIUM_LOGS
from database.config_db import mdb
from database.admin_settings_db import get_setting
from database.users_chats_db import db

PAYMENTS = mdb.db["premium_payments"]

PLANS = {
    "bronze": {"name": "🥉 Bronze", "days": 7, "price": Decimal("10")},
    "silver": {"name": "🥈 Silver", "days": 15, "price": Decimal("20")},
    "gold": {"name": "🥇 Gold", "days": 30, "price": Decimal("40")},
    "platinum": {"name": "💘 Platinum", "days": 45, "price": Decimal("55")},
    "diamond": {"name": "💎 Diamond", "days": 60, "price": Decimal("75")},
}

async def get_plan(plan_key):
    """Return the runtime plan, with safe DB overrides from Admin Panel."""
    base = PLANS.get(plan_key)
    if not base:
        return None
    try:
        overrides = await get_setting("premium_plans", {}) or {}
        cfg = overrides.get(plan_key, {}) if isinstance(overrides, dict) else {}
        return {
            "name": base["name"],
            "days": max(1, int(cfg.get("days", base["days"]))),
            "price": Decimal(str(cfg.get("price", base["price"]))),
            "enabled": bool(cfg.get("enabled", True)),
        }
    except Exception:
        return {**base, "enabled": True}

async def get_runtime_plans():
    result = {}
    for key in PLANS:
        result[key] = await get_plan(key)
    return result

BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-rpc.publicnode.com")
BSC_RPC_FALLBACK_URLS = [x.strip() for x in os.getenv("BSC_RPC_FALLBACK_URLS", "").split(",") if x.strip()]
TRON_API_URL = os.getenv("TRON_API_URL", "https://api.trongrid.io")
TRON_API_KEY = os.getenv("TRON_API_KEY", "")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
TON_API_URL = os.getenv("TON_API_URL", "https://tonapi.io")
TON_API_KEY = os.getenv("TON_API_KEY", "")
COINGECKO_URL = os.getenv("COINGECKO_URL", "https://api.coingecko.com/api/v3/simple/price")

BSC_ADDRESS = os.getenv("USDT_BSC_RECEIVE_ADDRESS", os.getenv("BSC_RECEIVE_ADDRESS", "0x026c23cfc5a92ae64840d6d3a2c878451c902901")).strip()
TRON_ADDRESS = os.getenv("TRON_RECEIVE_ADDRESS", "TANrp5PJkheRtixvDRMWk5UTQXfuzc4NM1").strip()
SOL_ADDRESS = os.getenv("SOLANA_RECEIVE_ADDRESS", "Dw9sotQ9mMYqKStLyiuM58t92bePe6PJUVbHkfuBMqia").strip()
TON_ADDRESS = os.getenv("TON_RECEIVE_ADDRESS", "UQCKKV1AcAnsi8YUiqPZEHLSbDTJdpsahn-bl-zTU59inSAO").strip()
BSC_USDT = os.getenv("BSC_USDT_CONTRACT", "0x55d398326f99059fF775485246999027B3197955").strip()
TRON_USDT = os.getenv("TRON_USDT_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t").strip()
SOL_USDT = os.getenv("SOLANA_USDT_MINT", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB").strip()
TON_USDT = os.getenv("TON_USDT_MASTER", "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs").strip()

NETWORKS = {
    "bsc_usdt": ("USDT • BEP20", "USDT", "BSC", BSC_ADDRESS, 18),
    "tron_usdt": ("USDT • TRC20", "USDT", "TRON", TRON_ADDRESS, 6),
    "sol_usdt": ("USDT • Solana", "USDT", "Solana", SOL_ADDRESS, 6),
    "ton_usdt": ("USDT • TON", "USDT", "TON", TON_ADDRESS, 6),
    "bnb": ("BNB • BSC", "BNB", "BSC", BSC_ADDRESS, 18),
    "trx": ("TRX • TRON", "TRX", "TRON", TRON_ADDRESS, 6),
    "sol": ("SOL • Solana", "SOL", "Solana", SOL_ADDRESS, 9),
    "ton": ("TON • TON", "TON", "TON", TON_ADDRESS, 9),
}
COIN_IDS = {"USDT": "tether", "BNB": "binancecoin", "TRX": "tron", "SOL": "solana", "TON": "the-open-network"}

# Telegram Stars: XTR invoices use whole Stars. Keep the INR conversion configurable
# so the bot never relies on a hard-coded provider exchange rate.
STARS_ENABLED = str(os.getenv("STARS_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}
STARS_PER_INR = Decimal(str(os.getenv("STARS_PER_INR", "1")))

def stars_amount(price):
    amount = (Decimal(str(price)) * STARS_PER_INR).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return max(1, int(amount))


async def ensure_payment_indexes():
    """Create payment safety indexes once at startup.

    tx_hash is unique when present so the same blockchain transaction cannot
    be used to finish two different crypto orders. Order IDs and submitted
    UTRs are also protected against accidental duplicates.
    """
    await PAYMENTS.create_index([("order_id", ASCENDING)], unique=True, name="uniq_payment_order_id")
    await PAYMENTS.create_index(
        [("tx_hash", ASCENDING)],
        unique=True,
        partialFilterExpression={"tx_hash": {"$type": "string", "$gt": ""}},
        name="uniq_crypto_tx_hash",
    )
    await PAYMENTS.create_index(
        [("payment_type", ASCENDING), ("utr", ASCENDING)],
        unique=True,
        partialFilterExpression={"payment_type": "upi", "utr": {"$type": "string", "$gt": ""}},
        name="uniq_upi_utr",
    )
    await PAYMENTS.create_index(
        [("telegram_payment_charge_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"telegram_payment_charge_id": {"$type": "string", "$gt": ""}},
        name="uniq_stars_charge_id",
    )


def _now():
    return datetime.now(timezone.utc)


async def plan_keyboard():
    rows = []
    plans = await get_runtime_plans()
    for key, p in plans.items():
        if p.get("enabled", True):
            rows.append([InlineKeyboardButton(f"{p['name']} • ₹{p['price']:.0f} / {p['days']} Days", callback_data=f"payplan_{key}")])
    if not rows:
        rows.append([InlineKeyboardButton("⚠️ No plans available", callback_data="premium_info")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="premium_info")])
    return InlineKeyboardMarkup(rows)


def method_keyboard(plan_key):
    # Synchronous fallback used only by error paths. The normal checkout uses
    # async_method_keyboard so Admin Panel toggles are applied immediately.
    rows = [
        [InlineKeyboardButton("💳 UPI • Screenshot / UTR", callback_data=f"payupi_{plan_key}")],
        [InlineKeyboardButton("🪙 USDT / Crypto • Automatic", callback_data=f"paycrypto_{plan_key}")],
    ]
    if STARS_ENABLED:
        rows.append([InlineKeyboardButton(f"⭐ Telegram Stars • {stars_amount(PLANS[plan_key]['price'])} XTR", callback_data=f"paystars_{plan_key}")])
    rows.append([InlineKeyboardButton("⬅️ Change Plan", callback_data="payplans")])
    return InlineKeyboardMarkup(rows)

async def async_method_keyboard(plan_key):
    rows = []
    if await get_setting("payment_upi_enabled", True):
        rows.append([InlineKeyboardButton("💳 UPI • Screenshot / UTR", callback_data=f"payupi_{plan_key}")])
    if await get_setting("payment_crypto_enabled", True):
        rows.append([InlineKeyboardButton("🪙 USDT / Crypto • Automatic", callback_data=f"paycrypto_{plan_key}")])
    if STARS_ENABLED and await get_setting("payment_stars_enabled", True):
        rows.append([InlineKeyboardButton(f"⭐ Telegram Stars • {stars_amount((await get_plan(plan_key))['price'])} XTR", callback_data=f"paystars_{plan_key}")])
    rows.append([InlineKeyboardButton("⬅️ Change Plan", callback_data="payplans")])
    return InlineKeyboardMarkup(rows)


def crypto_keyboard(plan_key):
    rows = []
    for key, (name, *_rest) in NETWORKS.items():
        address = NETWORKS[key][3]
        if address:
            rows.append([InlineKeyboardButton(name, callback_data=f"paynet_{plan_key}_{key}")])
    rows.append([InlineKeyboardButton("⬅️ Payment Methods", callback_data=f"paymethod_{plan_key}")])
    return InlineKeyboardMarkup(rows)


def _upi_uri(amount, order_id):
    vpa = OWNER_UPI_ID.strip()
    if not vpa:
        return ""
    return ("upi://pay?pa=" + quote(vpa) + "&pn=" + quote(os.getenv("UPI_PAYEE_NAME", "Premium")) +
            "&am=" + quote(f"{amount:.2f}") + "&cu=INR&tn=" + quote(f"Premium {order_id}"))


def _qr_bytes(data):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(data); qr.make(fit=True)
    image = qr.make_image()
    bio = io.BytesIO(); bio.name = "upi_qr.png"; image.save(bio, "PNG"); bio.seek(0)
    return bio


def _network_rate_symbol(symbol):
    return COIN_IDS.get(symbol)

async def crypto_amount(price, network_key):
    symbol = NETWORKS[network_key][1]
    coin = _network_rate_symbol(symbol)
    if not coin:
        raise RuntimeError("Unsupported coin")
    params = {"ids": coin, "vs_currencies": "inr"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        async with s.get(COINGECKO_URL, params=params) as r:
            if r.status >= 400:
                raise RuntimeError("Rate provider unavailable")
            data = await r.json()
    rate = Decimal(str(data[coin]["inr"]))
    if rate <= 0: raise RuntimeError("Invalid live rate")
    amount = (Decimal(price) / rate).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return amount, rate

async def _rpc(url, payload):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.post(url, json=payload) as r:
                if r.status >= 400: return None
                return await r.json()
    except Exception:
        return None

async def verify_bsc(p):
    target = p["address"].lower(); symbol = p["symbol"]
    urls = [BSC_RPC_URL] + BSC_RPC_FALLBACK_URLS
    head = None
    for url in urls:
        data = await _rpc(url, {"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]})
        if data and data.get("result"):
            head = int(data["result"], 16); break
    if head is None: return False, None
    final_head = max(0, head - 2)
    if symbol == "USDT":
        topic0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        topic2 = "0x" + target.removeprefix("0x").rjust(64, "0")
        wanted = int(Decimal(str(p["amount_crypto"])) * Decimal(10**6))
        start = max(0, int(p.get("scan_cursor", max(0, final_head-4000))) - 1500)
        for a in range(start, final_head+1, 500):
            b = min(final_head, a+499)
            for url in urls:
                data = await _rpc(url, {"jsonrpc":"2.0","id":2,"method":"eth_getLogs","params":[{"address":BSC_USDT,"fromBlock":hex(a),"toBlock":hex(b),"topics":[topic0,None,topic2]}]})
                if data is None: continue
                for log in data.get("result", []):
                    try:
                        if log.get("address","").lower() != BSC_USDT.lower(): continue
                        got = int(log.get("data","0x0"),16)
                        if got == wanted:
                            return True, log.get("transactionHash")
                    except Exception: pass
                break
            await PAYMENTS.update_one({"_id":p["_id"]},{"$set":{"scan_cursor":b}})
        return False, None
    for block in range(final_head, max(0,final_head-2000), -1):
        for url in urls:
            data = await _rpc(url,{"jsonrpc":"2.0","id":3,"method":"eth_getBlockByNumber","params":[hex(block),True]})
            if not data or not data.get("result"): continue
            for tx in data["result"].get("transactions",[]):
                try:
                    if (tx.get("to") or "").lower()!=target: continue
                    got=Decimal(int(tx.get("value","0x0"),16))/Decimal(10**18)
                    if got==Decimal(str(p["amount_crypto"])): return True,tx.get("hash")
                except Exception: pass
            break
    return False,None

async def verify_tron(p):
    headers={"TRON-PRO-API-KEY":TRON_API_KEY} if TRON_API_KEY else {}
    params={"limit":200,"only_confirmed":"true"}
    symbol=p["symbol"]
    url=f"{TRON_API_URL}/v1/accounts/{p['address']}/transactions/trc20" if symbol=="USDT" else f"{TRON_API_URL}/v1/accounts/{p['address']}/transactions"
    if symbol=="USDT": params["contract_address"]=TRON_USDT
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url,params=params,headers=headers) as r:
                if r.status>=400:return False,None
                data=await r.json()
    except Exception:return False,None
    wanted=Decimal(str(p["amount_crypto"]))
    for tx in data.get("data",[]):
        try:
            if symbol=="USDT":
                if tx.get("to")!=p["address"] or tx.get("token_info",{}).get("address")!=TRON_USDT: continue
                got=Decimal(str(tx.get("value",0)))/Decimal(10**6)
            else:
                if tx.get("to") != p["address"]:
                    continue
                raw = tx.get("raw_data", {}).get("contract", [])
                matched = False
                for contract in raw:
                    value = contract.get("parameter", {}).get("value", {})
                    if value.get("to_address") == p["address"]:
                        amount_sun = int(value.get("amount", 0))
                        got = Decimal(amount_sun) / Decimal(10**6)
                        matched = True
                        break
                if not matched:
                    continue
            if got == wanted:
                return True,tx.get("transaction_id") or tx.get("txID")
        except Exception:pass
    return False,None

async def verify_solana(p):
    sigs=await _rpc(SOLANA_RPC_URL,{"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":[p["address"],{"limit":100}]})
    if not sigs:return False,None
    wanted=Decimal(str(p["amount_crypto"]))
    for item in sigs.get("result",[]):
        if item.get("err"):continue
        sig=item.get("signature")
        txd=await _rpc(SOLANA_RPC_URL,{"jsonrpc":"2.0","id":2,"method":"getTransaction","params":[sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]})
        tx=(txd or {}).get("result")
        if not tx:continue
        meta=tx.get("meta") or {}
        if p["symbol"]=="SOL":
            keys=tx.get("transaction",{}).get("message",{}).get("accountKeys",[])
            for i,k in enumerate(keys):
                pub=k.get("pubkey") if isinstance(k,dict) else k
                if pub==p["address"] and i<len(meta.get("postBalances",[])):
                    delta=Decimal(meta["postBalances"][i]-meta["preBalances"][i])/Decimal(10**9)
                    if delta==wanted:return True,sig
        else:
            for bal in meta.get("postTokenBalances",[]):
                if bal.get("owner")!=p["address"] or bal.get("mint")!=SOL_USDT:continue
                idx=bal.get("accountIndex")
                post=Decimal(str(bal.get("uiTokenAmount",{}).get("amount",0)))/Decimal(10**6)
                pre=Decimal(0)
                for pb in meta.get("preTokenBalances",[]):
                    if pb.get("accountIndex")==idx and pb.get("mint")==SOL_USDT:
                        pre=Decimal(str(pb.get("uiTokenAmount",{}).get("amount",0)))/Decimal(10**6);break
                if post-pre==wanted:return True,sig
    return False,None

async def verify_ton(p):
    headers={"Authorization":f"Bearer {TON_API_KEY}"} if TON_API_KEY else {}
    address=p["address"]; wanted=Decimal(str(p["amount_crypto"]))
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            if p["symbol"]=="TON":
                url=f"{TON_API_URL}/v2/blockchain/accounts/{address}/transactions"
                async with s.get(url,params={"limit":100},headers=headers) as r:
                    if r.status>=400:return False,None
                    data=await r.json()
                for tx in data.get("transactions",[]):
                    msg=tx.get("in_msg") or {}
                    msgs=msg if isinstance(msg,list) else [msg]
                    for m in msgs:
                        if m.get("destination") not in (None,address):continue
                        try:
                            got=Decimal(str(m.get("value",0)))/Decimal(10**9)
                            if got==wanted:return True,tx.get("hash")
                        except Exception:pass
            else:
                url=f"{TON_API_URL}/v2/accounts/{address}/jettons/transfers"
                async with s.get(url,params={"jetton_master":TON_USDT,"limit":100},headers=headers) as r:
                    if r.status>=400:return False,None
                    data=await r.json()
                for item in data.get("transfers",[]):
                    if item.get("recipient",{}).get("address") not in (None,address):continue
                    try:
                        got=Decimal(str(item.get("amount",0)))/Decimal(10**6)
                        if got==wanted:return True,item.get("transaction_hash") or item.get("tx_hash")
                    except Exception:pass
    except Exception:return False,None
    return False,None

async def verify_crypto(p):
    network=p["network"]
    if network=="BSC": return await verify_bsc(p)
    if network=="TRON": return await verify_tron(p)
    if network=="Solana": return await verify_solana(p)
    if network=="TON": return await verify_ton(p)
    return False,None

async def activate_premium(user_id, days):
    now=datetime.now()
    user=await db.get_user(int(user_id)) or {"id":int(user_id)}
    old=user.get("expiry_time")
    if isinstance(old, datetime):
        base=max(now,old)
    else: base=now
    user["expiry_time"]=base+timedelta(days=int(days))
    await db.update_user(user)
    return user["expiry_time"]

async def _finish_crypto(payment, tx_hash):
    tx_hash = str(tx_hash or "").strip()
    if not tx_hash:
        return False
    # Fast duplicate check; the unique MongoDB index below is the race-safe
    # enforcement when two refresh workers see the same blockchain transfer.
    existing = await PAYMENTS.find_one({
        "tx_hash": tx_hash,
        "_id": {"$ne": payment["_id"]},
        "status": {"$in": ["verified", "finished", "processing"]},
    })
    if existing:
        return False
    try:
        claim = await PAYMENTS.find_one_and_update(
            {"_id": payment["_id"], "status": "pending"},
            {"$set": {"status": "verified", "tx_hash": tx_hash, "verified_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # Same blockchain transaction was already consumed by another order.
        return False
    if not claim:
        return False
    expiry = await activate_premium(claim["user_id"], claim["days"])
    await PAYMENTS.update_one({"_id":claim["_id"]},{"$set":{"status":"finished","premium_expiry":expiry}})
    return True

async def start_stars(client, query, plan_key):
    if not await get_setting("payment_stars_enabled", True):
        return await query.answer("Telegram Stars payment is disabled by admin.", show_alert=True)
    if not STARS_ENABLED:
        return await query.answer("Telegram Stars payment is currently unavailable.", show_alert=True)
    p = await get_plan(plan_key)
    if not p:
        return await query.answer("Invalid plan.", show_alert=True)
    if not p.get("enabled", True):
        return await query.answer("This Premium plan is currently disabled by admin.", show_alert=True)
    amount = stars_amount(p["price"])
    order = f"STARS-{query.from_user.id}-{uuid.uuid4().hex[:12].upper()}"
    now = _now()
    doc = {
        "order_id": order,
        "user_id": query.from_user.id,
        "plan": plan_key,
        "days": p["days"],
        "amount_inr": float(p["price"]),
        "amount_stars": amount,
        "currency": "XTR",
        "payment_type": "telegram_stars",
        "status": "pending",
        "created_at": now,
        "expires_at": now + timedelta(minutes=int(os.getenv("STARS_PAYMENT_EXPIRY_MINUTES", "30"))),
    }
    try:
        result = await PAYMENTS.insert_one(doc)
        payload = f"premium_stars:{result.inserted_id}"
        invoice = await client.send_invoice(
            chat_id=query.from_user.id,
            title=f"{p['name']} Premium",
            description=f"Premium access for {p['days']} days",
            currency="XTR",
            prices=LabeledPrice(p["name"], amount),
            payload=payload,
        )
        await PAYMENTS.update_one(
            {"_id": result.inserted_id},
            {"$set": {"invoice_message_id": invoice.id, "invoice_chat_id": query.from_user.id, "stars_payload": payload}},
        )
    except Exception as e:
        await PAYMENTS.update_one({"_id": result.inserted_id, "status": "pending"}, {"$set": {"status": "failed", "error": str(e)[:500], "failed_at": _now()}})
        try:
            await query.message.edit_text("⚠️ Telegram Stars invoice could not be created. Please choose another payment method or try again.", reply_markup=await async_method_keyboard(plan_key))
        except Exception:
            pass
        return
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.answer("⭐ Stars invoice created. Tap Pay to continue.")


async def stars_pre_checkout_handler(client, query):
    payload = str(query.invoice_payload or "")
    if not payload.startswith("premium_stars:"):
        return await client.answer_pre_checkout_query(query.id, success=False, error="Invalid payment order.")
    try:
        oid = ObjectId(payload.split(":", 1)[1])
    except Exception:
        return await client.answer_pre_checkout_query(query.id, success=False, error="Invalid payment order.")
    p = await PAYMENTS.find_one({"_id": oid, "payment_type": "telegram_stars", "status": "pending", "user_id": query.from_user.id})
    if not p:
        return await client.answer_pre_checkout_query(query.id, success=False, error="This payment order is invalid or already completed.")
    if p.get("expires_at") and p["expires_at"] <= _now():
        await PAYMENTS.update_one({"_id": oid, "status": "pending"}, {"$set": {"status": "expired", "expired_at": _now()}})
        return await client.answer_pre_checkout_query(query.id, success=False, error="This payment order has expired. Please create a new one.")
    if str(query.currency or "") != "XTR" or int(query.total_amount or 0) != int(p["amount_stars"]):
        return await client.answer_pre_checkout_query(query.id, success=False, error="Payment amount mismatch. Please create a new payment.")
    await client.answer_pre_checkout_query(query.id, success=True)


async def stars_successful_payment_handler(client, message):
    sp = message.successful_payment
    if not sp:
        return
    payload = str(sp.invoice_payload or "")
    if not payload.startswith("premium_stars:"):
        return
    try:
        oid = ObjectId(payload.split(":", 1)[1])
    except Exception:
        return await message.reply_text("⚠️ Payment received, but the order reference is invalid. Please contact support.")
    p = await PAYMENTS.find_one({"_id": oid, "payment_type": "telegram_stars", "user_id": message.from_user.id})
    if not p:
        return await message.reply_text("⚠️ Payment received, but the order record was not found. Please contact support.")
    charge_id = str(sp.telegram_payment_charge_id or "")
    if int(sp.total_amount or 0) != int(p.get("amount_stars", 0)) or str(sp.currency or "") != "XTR":
        await PAYMENTS.update_one({"_id": oid}, {"$set": {"status": "amount_mismatch", "charge_id": charge_id, "mismatch_at": _now()}})
        return await message.reply_text("⚠️ Payment received but the amount could not be safely matched. Please contact support.")
    claim = await PAYMENTS.find_one_and_update(
        {"_id": oid, "status": "pending"},
        {"$set": {"status": "processing", "telegram_payment_charge_id": charge_id, "provider_payment_charge_id": str(sp.provider_payment_charge_id or ""), "paid_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if not claim:
        return
    expiry = await activate_premium(claim["user_id"], claim["days"])
    await PAYMENTS.update_one({"_id": oid, "status": "processing"}, {"$set": {"status": "finished", "premium_expiry": expiry, "verified_at": _now()}})
    try:
        await message.reply_text(
            f"🎉 <b>Telegram Stars Payment Successful!</b>\n\n"
            f"💎 Plan: <b>{(await get_plan(claim['plan']))['name']}</b>\n"
            f"⭐ Paid: <b>{claim['amount_stars']} Stars</b>\n"
            f"⏰ Duration: <b>{claim['days']} days</b>\n\n"
            f"✅ <b>Premium is now active.</b>\n"
            f"⌛ Expiry: <code>{expiry.strftime('%d-%m-%Y %I:%M %p')}</code>\n\n"
            f"🧾 Order: <code>{claim['order_id']}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass


@Client.on_pre_checkout_query()
async def _stars_pre_checkout_event(client, query):
    await stars_pre_checkout_handler(client, query)


@Client.on_message(filters.private & filters.successful_payment)
async def _stars_success_event(client, message):
    await stars_successful_payment_handler(client, message)


async def show_plan_checkout(client, query, plan_key):
    p=await get_plan(plan_key)
    if not p or not p.get("enabled", True):
        return await query.answer("This Premium plan is currently disabled by admin.", show_alert=True)
    methods = []
    if await get_setting("payment_upi_enabled", True): methods.append("💳 UPI = screenshot/UTR + admin verification")
    if await get_setting("payment_crypto_enabled", True): methods.append("🪙 Crypto = automatic blockchain verification")
    if STARS_ENABLED and await get_setting("payment_stars_enabled", True): methods.append(f"⭐ Telegram Stars = {stars_amount(p['price'])} Stars + automatic activation")
    method_text = "\n".join(methods) if methods else "❌ No payment method is currently enabled by admin."
    text=(f"💎 <b>{p['name']} PREMIUM</b>\n━━━━━━━━━━━━━━━━━━\n\n"
          f"⏰ Duration: <b>{p['days']} days</b>\n💰 Price: <b>₹{p['price']:.0f}</b>\n\n"
          f"<b>Select a payment method:</b>\n{method_text}")
    await query.message.edit_text(text,reply_markup=await async_method_keyboard(plan_key))

async def start_upi(client, query, plan_key):
    if not await get_setting("payment_upi_enabled", True):
        return await query.answer("UPI payment is disabled by admin.", show_alert=True)
    p=await get_plan(plan_key)
    if not p or not p.get("enabled", True):
        return await query.answer("This Premium plan is currently disabled by admin.", show_alert=True)
    order=f"UPI-{query.from_user.id}-{uuid.uuid4().hex[:10].upper()}"
    doc={"order_id":order,"user_id":query.from_user.id,"plan":plan_key,"days":p["days"],"amount_inr":float(p["price"]),"payment_type":"upi","status":"awaiting_proof","created_at":_now(),"expires_at":_now()+timedelta(minutes=int(os.getenv("UPI_PAYMENT_EXPIRY_MINUTES","60")))}
    res=await PAYMENTS.insert_one(doc); ref=str(res.inserted_id)
    uri=_upi_uri(p["price"],order)
    text=(f"💳 <b>UPI PAYMENT</b>\n━━━━━━━━━━━━━━━━━━\n\n{p['name']} • {p['days']} Days\n💰 Exact Amount: <b>₹{p['price']:.2f}</b>\n\n📌 UPI ID: <code>{OWNER_UPI_ID}</code>\n🧾 Order ID: <code>{order}</code>\n\n1️⃣ Pay the exact amount.\n2️⃣ Tap <b>I've Paid</b>.\n3️⃣ Submit either your <b>UTR / transaction reference</b> OR a <b>payment screenshot</b>.\n4️⃣ Admin will verify the proof manually. <b>Premium activates only after approval.</b>\n\n⚠️ Screenshot must clearly show the payment status, amount and transaction/reference details.\n⚠️ Do not send OTP, UPI PIN or banking password.")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📲 Pay via UPI",url=uri)] if uri else [InlineKeyboardButton("📌 UPI ID",callback_data=f"upi_copy_{ref}")], [InlineKeyboardButton("✅ I've Paid • Submit Proof",callback_data=f"upisubmit_{ref}")],[InlineKeyboardButton("❌ Cancel",callback_data="payplans")]])
    try:
        await query.message.delete()
    except Exception:
        pass
    if uri:
        await client.send_photo(query.from_user.id, photo=_qr_bytes(uri), caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await client.send_message(query.from_user.id, text, reply_markup=kb, parse_mode="HTML")

async def start_crypto(client, query, plan_key):
    if not await get_setting("payment_crypto_enabled", True):
        return await query.answer("Crypto payment is disabled by admin.", show_alert=True)
    await query.message.edit_text("🪙 <b>Select Crypto Network</b>\n\nUSDT and native coins are supported where a receiving address is configured.",reply_markup=crypto_keyboard(plan_key))

async def start_crypto_order(client, query, plan_key, network_key):
    if not await get_setting("payment_crypto_enabled", True):
        return await query.answer("Crypto payment is disabled by admin.", show_alert=True)
    p=await get_plan(plan_key)
    if not p or not p.get("enabled", True):
        return await query.answer("This Premium plan is currently disabled by admin.", show_alert=True)
    name,symbol,network,address,decimals=NETWORKS[network_key]
    if not address:
        return await query.answer("This network is not configured by admin.",show_alert=True)
    try: amount,rate=await crypto_amount(p["price"],network_key)
    except Exception:
        return await query.answer("Live crypto rate is unavailable. Please try again.",show_alert=True)
    order=f"CRYPTO-{query.from_user.id}-{uuid.uuid4().hex[:10].upper()}"
    res=await PAYMENTS.insert_one({"order_id":order,"user_id":query.from_user.id,"plan":plan_key,"days":p["days"],"amount_inr":float(p["price"]),"amount_crypto":str(amount),"symbol":symbol,"network":network,"network_key":network_key,"address":address,"exchange_rate":float(rate),"payment_type":"crypto","status":"pending","created_at":_now(),"expires_at":_now()+timedelta(minutes=int(os.getenv("PAYMENT_EXPIRY_MINUTES","60")))})
    ref=str(res.inserted_id)
    text=(f"🪙 <b>{name}</b>\n━━━━━━━━━━━━━━━━━━\n\n{p['name']} • {p['days']} Days\n💰 Value: ₹{p['price']:.2f}\n\n📤 Send EXACTLY:\n<code>{amount}</code> <b>{symbol}</b>\n\n📍 Address:\n<code>{address}</code>\n\n🌐 Network: <b>{network}</b>\n🧾 Order: <code>{order}</code>\n\n⚠️ Exact amount + exact network only. After sending, tap Refresh Payment.")
    await query.message.edit_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Payment",callback_data=f"cryptorefresh_{ref}")],[InlineKeyboardButton("⬅️ Change Network",callback_data=f"paycrypto_{plan_key}")],[InlineKeyboardButton("❌ Cancel",callback_data="payplans")]]))

async def _send_upi_review(client, p, proof_type="UTR", proof_value=None, screenshot_file_id=None, screenshot_media_type="photo"):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ APPROVE & ACTIVATE", callback_data=f"payapprove_{p['_id']}")],
        [InlineKeyboardButton("❌ CANCEL • MOVE TO PAYMENT LOGS", callback_data=f"paycancel_{p['_id']}")],
    ])
    proof_line = f"🔢 UTR: <code>{proof_value}</code>" if proof_value else "📸 Proof: <b>Payment screenshot attached</b>"
    admin_text = (f"🔔 <b>NEW UPI PAYMENT REVIEW</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                  f"👤 User ID: <code>{p['user_id']}</code>\n"
                  f"💎 Plan: <b>{(await get_plan(p['plan']))['name']}</b>\n"
                  f"⏰ Days: {p['days']}\n"
                  f"💰 Amount: ₹{p['amount_inr']:.2f}\n"
                  f"🧾 Order: <code>{p['order_id']}</code>\n"
                  f"{proof_line}\n\n"
                  f"⚠️ Verify the payment in your UPI/bank app before approving.\n"
                  f"If you accidentally press Cancel, the payment is moved to Payment Logs with the approval option preserved.")
    for admin in ADMINS:
        try:
            if screenshot_file_id:
                if screenshot_media_type == "document":
                    await client.send_document(int(admin), screenshot_file_id, caption=admin_text, reply_markup=buttons, parse_mode="HTML")
                else:
                    await client.send_photo(int(admin), screenshot_file_id, caption=admin_text, reply_markup=buttons, parse_mode="HTML")
            else:
                await client.send_message(int(admin), admin_text, reply_markup=buttons, parse_mode="HTML")
        except Exception:
            pass
    if PREMIUM_LOGS:
        try:
            if screenshot_file_id:
                if screenshot_media_type == "document":
                    await client.send_document(PREMIUM_LOGS, screenshot_file_id, caption=admin_text, reply_markup=buttons, parse_mode="HTML")
                else:
                    await client.send_photo(PREMIUM_LOGS, screenshot_file_id, caption=admin_text, reply_markup=buttons, parse_mode="HTML")
            else:
                await client.send_message(PREMIUM_LOGS, admin_text, reply_markup=buttons, parse_mode="HTML")
        except Exception:
            pass

async def submit_utr(client, message, ref):
    utr=message.text.strip().replace(" ","")
    if not (8<=len(utr)<=32 and utr.isalnum()):
        await message.reply_text("❌ Invalid UTR/reference. Please send the transaction reference exactly as shown by your UPI app.")
        return
    try: oid=ObjectId(ref)
    except Exception:return
    p0=await PAYMENTS.find_one({"_id":oid,"user_id":message.from_user.id,"status":"awaiting_utr","proof_mode":"utr"})
    if not p0:
        await message.reply_text("⚠️ This payment request is no longer awaiting payment proof.")
        return
    if p0.get("expires_at") and p0["expires_at"] <= _now():
        await PAYMENTS.update_one({"_id":oid,"status":"awaiting_utr","proof_mode":"utr"},{"$set":{"status":"expired","expired_at":_now()}})
        await message.reply_text("⏰ This UPI payment request has expired. Please create a new payment.")
        return
    duplicate=await PAYMENTS.find_one({"payment_type":"upi","utr":utr,"_id":{"$ne":oid},"status":{"$in":["pending_review","processing","finished","cancelled_review"]}})
    if duplicate:
        await message.reply_text("❌ This UTR/reference has already been submitted for another payment order. Please check the transaction reference and submit the correct one.")
        return
    p=await PAYMENTS.find_one_and_update(
        {"_id":oid,"user_id":message.from_user.id,"status":"awaiting_utr","proof_mode":"utr"},
        {"$set":{"utr":utr,"status":"pending_review","proof_type":"utr","utr_submitted_at":_now(),"proof_submitted_at":_now()}},
        return_document=ReturnDocument.AFTER)
    if not p:
        await message.reply_text("⚠️ This payment request is no longer awaiting payment proof.")
        return
    await message.reply_text(f"✅ <b>UTR submitted.</b>\n\n🧾 Order: <code>{p['order_id']}</code>\n💰 Amount: ₹{p['amount_inr']:.2f}\n\n⏳ Your payment proof is now <b>pending admin verification</b>. Premium will activate only after approval.", parse_mode="HTML")
    await _send_upi_review(client, p, "UTR", utr)

async def submit_screenshot(client, message, ref):
    photo = message.photo
    if not photo:
        return
    try: oid=ObjectId(ref)
    except Exception:return
    p0=await PAYMENTS.find_one({"_id":oid,"user_id":message.from_user.id,"status":"awaiting_screenshot"})
    if not p0:
        await message.reply_text("⚠️ This payment request is no longer awaiting payment proof.")
        return
    if p0.get("expires_at") and p0["expires_at"] <= _now():
        await PAYMENTS.update_one({"_id":oid,"status":"awaiting_screenshot"},{"$set":{"status":"expired","expired_at":_now()}})
        await message.reply_text("⏰ This UPI payment request has expired. Please create a new payment.")
        return
    p=await PAYMENTS.find_one_and_update(
        {"_id":oid,"user_id":message.from_user.id,"status":"awaiting_screenshot"},
        {"$set":{"status":"pending_review","proof_type":"screenshot","screenshot_file_id":str(photo.file_id),"screenshot_media_type":"photo","screenshot_submitted_at":_now(),"proof_submitted_at":_now()}},
        return_document=ReturnDocument.AFTER)
    if not p:
        await message.reply_text("⚠️ This payment request is no longer awaiting payment proof.")
        return
    await message.reply_text(f"✅ <b>Payment screenshot received.</b>\n\n🧾 Order: <code>{p['order_id']}</code>\n💰 Amount: ₹{p['amount_inr']:.2f}\n\n⏳ Your screenshot is now <b>pending admin verification</b>. Premium will activate only after approval.", parse_mode="HTML")
    await _send_upi_review(client, p, "Screenshot", screenshot_file_id=photo.file_id, screenshot_media_type="photo")

async def _copy_payment_to_logs(client, p, note="🗂 MOVED TO PAYMENT LOGS"):
    if not PREMIUM_LOGS:
        return False
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ APPROVE & ACTIVATE", callback_data=f"payapprove_{p['_id']}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"paycancel_{p['_id']}")],
    ])
    proof = f"🔢 UTR: <code>{p.get('utr')}</code>" if p.get('utr') else "📸 Proof: <b>Payment screenshot attached</b>"
    text=(f"🗂 <b>PAYMENT LOGS • UPI REVIEW</b>\n━━━━━━━━━━━━━━━━━━\n\n"
          f"👤 User ID: <code>{p['user_id']}</code>\n"
          f"💎 Plan: <b>{(await get_plan(p['plan']))['name']}</b>\n"
          f"⏰ Days: {p['days']}\n💰 Amount: ₹{p['amount_inr']:.2f}\n"
          f"🧾 Order: <code>{p['order_id']}</code>\n{proof}\n\n"
          f"{note}\n✅ Approval option is still available here.")
    try:
        if p.get("screenshot_file_id"):
            if p.get("screenshot_media_type") == "document":
                await client.send_document(PREMIUM_LOGS, p["screenshot_file_id"], caption=text, reply_markup=buttons, parse_mode="HTML")
            else:
                await client.send_photo(PREMIUM_LOGS, p["screenshot_file_id"], caption=text, reply_markup=buttons, parse_mode="HTML")
        else:
            await client.send_message(PREMIUM_LOGS, text, reply_markup=buttons, parse_mode="HTML")
        return True
    except Exception:
        return False

async def admin_payment_action(client, query, ref, approve):
    if int(query.from_user.id) not in [int(x) for x in ADMINS]:
        return await query.answer("Admin only.",show_alert=True)
    try: oid=ObjectId(ref)
    except Exception:return await query.answer("Invalid payment.",show_alert=True)
    p=await PAYMENTS.find_one({"_id":oid})
    if not p:return await query.answer("Payment not found.",show_alert=True)
    status=p.get("status")
    if status not in {"pending_review","cancelled_review"}:
        return await query.answer(f"Already {status}.",show_alert=True)
    if not approve:
        # Do not destroy the reviewable payment. Mark it as cancelled/moved and
        # create a fresh Payment Logs entry with the approval control preserved.
        changed=await PAYMENTS.find_one_and_update(
            {"_id":oid,"status":status},
            {"$set":{"status":"cancelled_review","cancelled_at":_now(),"cancelled_by":query.from_user.id}},
            return_document=ReturnDocument.AFTER)
        if not changed:
            return await query.answer("Payment was already handled.",show_alert=True)
        try:
            if query.message.photo:
                await query.message.edit_caption((query.message.caption or "")+"\n\n🗂 <b>CANCELLED / MOVED TO PAYMENT LOGS</b>",reply_markup=None,parse_mode="HTML")
            else:
                await query.message.edit_text((query.message.text or "")+"\n\n🗂 <b>CANCELLED / MOVED TO PAYMENT LOGS</b>",reply_markup=None,parse_mode="HTML")
        except Exception: pass
        await _copy_payment_to_logs(client, changed)
        try: await client.send_message(p["user_id"],f"ℹ️ Your UPI payment proof for <b>{(await get_plan(p['plan']))['name']}</b> is still under review.\n\n🧾 Order: <code>{p['order_id']}</code>",parse_mode="HTML")
        except Exception: pass
        return await query.answer("Moved to Payment Logs. Approval is still available there.")
    claimed=await PAYMENTS.find_one_and_update(
        {"_id":oid,"status":status},
        {"$set":{"status":"processing","reviewed_by":query.from_user.id,"reviewed_at":_now()}},
        return_document=ReturnDocument.AFTER)
    if not claimed:return await query.answer("Could not claim payment.",show_alert=True)
    expiry=await activate_premium(claimed["user_id"],claimed["days"])
    await PAYMENTS.update_one({"_id":oid},{"$set":{"status":"finished","premium_expiry":expiry}})
    try:
        if query.message.photo:
            await query.message.edit_caption((query.message.caption or "")+f"\n\n✅ <b>APPROVED & PREMIUM ACTIVATED</b>\n⏳ Expiry: <code>{expiry.strftime('%d-%m-%Y %I:%M %p')}</code>",reply_markup=None,parse_mode="HTML")
        else:
            await query.message.edit_text((query.message.text or "")+f"\n\n✅ <b>APPROVED & PREMIUM ACTIVATED</b>\n⏳ Expiry: <code>{expiry.strftime('%d-%m-%Y %I:%M %p')}</code>",reply_markup=None,parse_mode="HTML")
    except Exception: pass
    try: await client.send_message(p["user_id"],f"🎉 <b>Premium activated!</b>\n\n💎 Plan: {(await get_plan(p['plan']))['name']}\n⏰ Duration: {p['days']} days\n🧾 Order: <code>{p['order_id']}</code>\n\n⌛ Expiry: <code>{expiry.strftime('%d-%m-%Y %I:%M %p')}</code>\n\nThank you for your purchase! ❤️",parse_mode="HTML")
    except Exception:pass
    await query.answer("Premium activated successfully.")

@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
async def premium_payment_text_handler(client, message):
    # Only consume text when this user has a payment waiting for a UTR.
    p=await PAYMENTS.find_one({"user_id":message.from_user.id,"status":"awaiting_utr","proof_mode":"utr"},sort=[("created_at",-1)])
    if not p:return
    await submit_utr(client,message,str(p["_id"]))



@Client.on_message(filters.private & filters.photo)
async def premium_payment_screenshot_handler(client, message):
    # A screenshot can be submitted instead of a UTR. The latest awaiting UPI
    # payment for this user is atomically claimed so duplicate screenshots do
    # not create multiple review records.
    p=await PAYMENTS.find_one({"user_id":message.from_user.id,"status":"awaiting_screenshot"},sort=[("created_at",-1)])
    if not p:
        return
    await submit_screenshot(client, message, str(p["_id"]))


@Client.on_message(filters.private & filters.document)
async def premium_payment_screenshot_document_handler(client, message):
    # Screenshots may also be sent as Telegram files/documents. Accept only
    # image MIME types while a UPI order is awaiting proof.
    document = message.document
    if not document or not str(document.mime_type or "").lower().startswith("image/"):
        return
    p = await PAYMENTS.find_one({"user_id": message.from_user.id, "status": "awaiting_screenshot"}, sort=[("created_at", -1)])
    if not p:
        return
    try:
        oid = ObjectId(str(p["_id"]))
    except Exception:
        return
    p0 = await PAYMENTS.find_one({"_id": oid, "user_id": message.from_user.id, "status": "awaiting_screenshot"})
    if not p0:
        await message.reply_text("⚠️ This payment request is no longer awaiting payment proof.")
        return
    if p0.get("expires_at") and p0["expires_at"] <= _now():
        await PAYMENTS.update_one({"_id": oid, "status": "awaiting_screenshot"}, {"$set": {"status": "expired", "expired_at": _now()}})
        await message.reply_text("⏰ This UPI payment request has expired. Please create a new payment.")
        return
    claimed = await PAYMENTS.find_one_and_update(
        {"_id": oid, "user_id": message.from_user.id, "status": "awaiting_screenshot"},
        {"$set": {
            "status": "pending_review",
            "proof_type": "screenshot",
            "screenshot_file_id": str(document.file_id),
            "screenshot_media_type": "document",
            "screenshot_submitted_at": _now(),
            "proof_submitted_at": _now(),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        await message.reply_text("⚠️ This payment request is no longer awaiting payment proof.")
        return
    await message.reply_text(
        f"✅ <b>Payment screenshot received.</b>\n\n"
        f"🧾 Order: <code>{claimed['order_id']}</code>\n"
        f"💰 Amount: ₹{claimed['amount_inr']:.2f}\n\n"
        f"⏳ Your screenshot is now <b>pending admin verification</b>. Premium will activate only after approval.",
        parse_mode="HTML",
    )
    await _send_upi_review(
        client, claimed, "Screenshot",
        screenshot_file_id=document.file_id,
        screenshot_media_type="document",
    )
