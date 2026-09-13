import asyncio
from datetime import datetime, timezone
from bson import ObjectId
from html import escape
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, REQST_CHANNEL, SUPPORT_CHAT_ID
from database.config_db import mdb
from database.admin_settings_db import get_setting

REQUESTS = mdb.db["movie_requests"]
REQUEST_DRAFTS = {}
ADMIN_REPLY_STATE = {}


def _now():
    return datetime.now(timezone.utc)


def _mention(user):
    try:
        return user.mention
    except Exception:
        return f"<a href='tg://user?id={user.id}'>{user.first_name or 'User'}</a>"


def request_prompt(query=None):
    if query:
        return (
            "📩 <b>Movie Request</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🔎 I couldn't find <b>{query}</b> in the database.\n\n"
            "Aap request bhejna chahte ho to neeche button dabao. "
            "Phir movie/series ka <b>exact title + year</b> bhej dena.\n\n"
            "💡 Spelling ka tension mat lo — hum title verify kar lenge."
        )
    return (
        "📩 <b>REQUEST A MOVIE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎬 Database mein movie/series nahi mil rahi?\n"
        "Yahan request bhejo.\n\n"
        "📝 <b>Best format:</b> Movie Name (Year)\n"
        "Example: <code>Interstellar (2014)</code>\n\n"
        "🔍 Team request check karke available status batayegi."
    )


def request_button(label="📩 Request This Movie"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="request_start")],
        [InlineKeyboardButton("🏠 Home", callback_data="ui_home")],
    ])


def admin_request_keyboard(ref):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Movie Uploaded", callback_data=f"req_uploaded_{ref}")],
        [InlineKeyboardButton("⏳ Not Released Yet", callback_data=f"req_unreleased_{ref}")],
        [InlineKeyboardButton("✏️ Title / Spelling Issue", callback_data=f"req_spelling_{ref}")],
        [InlineKeyboardButton("💬 Custom Reply", callback_data=f"req_reply_{ref}")],
    ])


def _admin_text(p, status=None):
    status_line = f"\n📌 Status: <b>{escape(str(status))}</b>" if status else ""
    mention = p.get("user_mention") or f"<code>{p['user_id']}</code>"
    return (
        "📩 <b>NEW MOVIE REQUEST</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🎬 Requested: <b>{escape(str(p['title']))}</b>\n"
        f"👤 User: {mention}\n"
        f"🆔 User ID: <code>{p['user_id']}</code>\n"
        f"🧾 Request ID: <code>{p['_id']}</code>\n"
        f"🕒 Submitted: <code>{p['created_at'].strftime('%d-%m-%Y %I:%M %p')}</code>"
        f"{status_line}\n\n"
        "👇 <b>Verify the request and choose an appropriate response:</b>"
    )


async def create_request(client, user, title, source="manual"):
    if not await get_setting("request_system_enabled", True):
        return False, "ℹ️ Movie requests are currently disabled by admin."
    title = " ".join(str(title or "").strip().split())
    if len(title) < 3:
        return False, "❌ Please send a valid movie/series title (minimum 3 characters)."
    if len(title) > 200:
        title = title[:200].rstrip()
    doc = {
        "user_id": int(user.id),
        "user_name": user.first_name or "User",
        "user_mention": user.mention,
        "title": title,
        "source": source,
        "status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
    }
    try:
        result = await REQUESTS.insert_one(doc)
        doc["_id"] = result.inserted_id
    except Exception:
        return False, "⚠️ Request could not be saved. Please try again."

    text = _admin_text(doc)
    kb = admin_request_keyboard(result.inserted_id)
    sent = False
    runtime_request_channel = await get_setting("request_channel", REQST_CHANNEL)
    if runtime_request_channel:
        try:
            await client.send_message(int(runtime_request_channel), text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
            sent = True
        except Exception:
            pass
    if not sent:
        for admin in ADMINS:
            try:
                await client.send_message(int(admin), text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
                sent = True
            except Exception:
                pass
    if sent:
        await REQUESTS.update_one({"_id": result.inserted_id}, {"$set": {"logged": True, "logged_at": _now()}})
        return True, (
            "✅ <b>Request received!</b>\n\n"
            f"🎬 <b>{title}</b>\n\n"
            "Your request has been sent to the admin team for checking. "
            "You will receive an update here after review."
        )
    return False, "⚠️ Request saved, but the request channel is currently unavailable. Admin will need to check the request logs."


async def start_request(client, user_id, title=None):
    if title:
        REQUEST_DRAFTS[int(user_id)] = str(title).strip()
    else:
        REQUEST_DRAFTS[int(user_id)] = ""


async def handle_user_request_text(client, message):
    user_id = int(message.from_user.id)
    if user_id not in REQUEST_DRAFTS:
        return False
    title = message.text.strip()
    REQUEST_DRAFTS.pop(user_id, None)
    ok, response = await create_request(client, message.from_user, title, source="button")
    await message.reply_text(response, parse_mode="HTML", disable_web_page_preview=True)
    return True


async def handle_request_callback(client, query):
    data = query.data
    user_id = int(query.from_user.id)

    if data == "request_start":
        # Preserve a title captured from a no-result search, otherwise start blank.
        REQUEST_DRAFTS.setdefault(user_id, "")
        await query.answer("Send the movie/series title now ✍️", show_alert=True)
        await query.message.reply_text(
            "✍️ <b>Send Movie Request</b>\n\n"
            "Ab movie/series ka <b>exact title</b> bhejo. Year bhi add karo agar possible ho.\n\n"
            "Example: <code>Inception (2010)</code>",
            parse_mode="HTML",
        )
        return True

    if not data.startswith("req_"):
        return False
    parts = data.split("_", 2)
    if len(parts) != 3:
        return False
    action, ref = parts[1], parts[2]
    if user_id not in [int(x) for x in ADMINS]:
        await query.answer("Admin only.", show_alert=True)
        return True
    try:
        oid = ObjectId(ref)
    except Exception:
        await query.answer("Invalid request.", show_alert=True)
        return True
    p = await REQUESTS.find_one({"_id": oid})
    if not p:
        await query.answer("Request not found.", show_alert=True)
        return True

    if action == "reply":
        if p.get("status") != "pending":
            await query.answer(f"Request is already {p.get('status', 'handled')}.", show_alert=True)
            return True
        ADMIN_REPLY_STATE[user_id] = str(oid)
        await query.answer("Send your custom reply now ✍️", show_alert=True)
        await query.message.reply_text(
            "💬 <b>Custom Reply Mode</b>\n\nSend the reply you want to deliver to the requester.\n"
            "Your next text message will be sent to the user.", parse_mode="HTML"
        )
        return True

    replies = {
        "uploaded": ("uploaded", "🎬 <b>Movie Uploaded</b>", "Good news! Your requested movie is now available in our database. 🔎\n\nPlease search the title again in the bot."),
        "unreleased": ("unreleased", "⏳ <b>Not Released Yet</b>", "This movie has not been officially released/available yet. ⏳\n\nPlease request it again after release."),
        "spelling": ("spelling", "✏️ <b>Title / Spelling Issue</b>", "We couldn't match the title exactly. ✏️\n\nPlease check the movie name/spelling and search again. If it still doesn't appear, send a new request."),
    }
    if action not in replies:
        return False
    status, admin_heading, user_reply = replies[action]
    changed = await REQUESTS.find_one_and_update(
        {"_id": oid, "status": "pending"},
        {"$set": {"status": status, "reviewed_by": user_id, "reviewed_at": _now(), "updated_at": _now()}},
    )
    if not changed:
        await query.answer("Request is already closed.", show_alert=True)
        return True
    try:
        await client.send_message(p["user_id"], user_reply, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        pass
    try:
        await query.message.edit_text(_admin_text(p, status=status) + f"\n\n{admin_heading}\n✅ Response sent to user.", reply_markup=None, parse_mode="HTML")
    except Exception:
        pass
    await query.answer("Response sent to user.")
    return True


async def handle_admin_reply_text(client, message):
    admin_id = int(message.from_user.id)
    ref = ADMIN_REPLY_STATE.get(admin_id)
    if not ref:
        return False
    ADMIN_REPLY_STATE.pop(admin_id, None)
    try:
        oid = ObjectId(ref)
    except Exception:
        await message.reply_text("⚠️ Invalid request reference.")
        return True
    p = await REQUESTS.find_one({"_id": oid})
    if not p:
        await message.reply_text("⚠️ Request not found.")
        return True
    reply = message.text.strip()
    if not reply:
        await message.reply_text("❌ Reply cannot be empty.")
        return True
    await REQUESTS.update_one({"_id": oid}, {"$set": {"status": "replied", "reviewed_by": admin_id, "reviewed_at": _now(), "admin_reply": reply, "updated_at": _now()}})
    try:
        await client.send_message(p["user_id"], f"💬 <b>Reply regarding your movie request</b>\n\n{escape(reply)}", parse_mode="HTML", disable_web_page_preview=True)
        await message.reply_text("✅ Custom reply sent to the requester.")
    except Exception:
        await message.reply_text("⚠️ Could not deliver the reply to the user. The reply has been saved in the request log.")
    return True


async def send_no_result_request(client, message, search):
    search = " ".join(str(search or "").split()).strip()
    REQUEST_DRAFTS[int(message.from_user.id)] = search
    return await message.reply_text(
        f"🔎 <b>No movie found</b>\n\n"
        f"I couldn't find <b>{search}</b> in the movie database.\n\n"
        "📩 If this is the movie you need, send a request and our admin team will check whether it is uploaded, unreleased, or the title needs correction.\n\n"
        "💡 <b>Spelling mistakes can happen</b> — don't worry, we'll verify the title.",
        reply_markup=request_button("📩 Request This Movie"),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
