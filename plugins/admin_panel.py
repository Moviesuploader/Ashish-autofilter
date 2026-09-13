import asyncio, os, time
from datetime import datetime, timezone
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat
from info import ADMINS, PICS
from database.users_chats_db import db
from database.config_db import mdb
from database.admin_settings_db import ensure_settings, get_setting, set_setting, get_all_settings, log_admin_action, get_index_state
from database.referral_db import ensure_indexes, get_dashboard

ADMIN_LABEL = "👑 JARVIS ADMIN PANEL"

def yn(v): return "🟢 ON" if v else "🔴 OFF"
def row(label, value, key):
    return [InlineKeyboardButton(f"{label}: {yn(value)}", callback_data=f"adm_toggle:{key}")]

async def _count_files():
    try:
        from database.ia_filterdb import Media, Media2
        return await Media.count_documents({}) + await Media2.count_documents({})
    except Exception:
        return 0

async def dashboard_text():
    users = await db.total_users_count()
    chats = await db.total_chat_count()
    premium = await db.all_premium_users()
    files = await _count_files()
    req = 0
    try:
        req = await mdb.db["movie_requests"].count_documents({"status": "pending"})
    except Exception:
        pass
    pending_pay = 0
    try:
        pending_pay = await mdb.db["premium_payments"].count_documents({"status": {"$in": ["awaiting_utr", "pending_review"]}})
    except Exception:
        pass
    s = await get_all_settings()
    return (f"{ADMIN_LABEL}\n━━━━━━━━━━━━━━━━━━\n"
            f"👥 Users: <b>{users}</b>   |   👥 Groups: <b>{chats}</b>\n"
            f"🎬 Indexed Files: <b>{files}</b>\n⭐ Premium Users: <b>{premium}</b>\n"
            f"📩 Pending Requests: <b>{req}</b>\n💳 Pending Payments: <b>{pending_pay}</b>\n\n"
            f"🤖 Bot: <b>{'MAINTENANCE' if s.get('maintenance_mode') else 'ONLINE'}</b>")

def dashboard_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Bot Controls", callback_data="adm_page:controls"), InlineKeyboardButton("💳 Payments", callback_data="adm_page:payments")],
        [InlineKeyboardButton("📡 Channels", callback_data="adm_page:channels"), InlineKeyboardButton("🤝 Referral", callback_data="adm_page:referral")],
        [InlineKeyboardButton("📩 Requests", callback_data="adm_page:requests"), InlineKeyboardButton("🎬 Catalogue", callback_data="adm_page:catalogue")],
        [InlineKeyboardButton("👥 Users", callback_data="adm_page:users"), InlineKeyboardButton("📢 Broadcast", callback_data="adm_page:broadcast")],
        [InlineKeyboardButton("🛡️ Security & Logs", callback_data="adm_page:security")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="adm_refresh")]
    ])

async def render_page(key):
    s = await get_all_settings()
    if key == "controls":
        text = "⚙️ <b>BOT CONTROLS</b>\n━━━━━━━━━━━━━━━━━━\nTap any switch to change it instantly."
        kb = [row("🛠 Maintenance", s.get("maintenance_mode"), "maintenance_mode"),
              row("🔗 Shortener", s.get("shortener_enabled"), "shortener_enabled"),
              row("📤 Content Forwarding", s.get("content_forwarding_enabled"), "content_forwarding_enabled"),
              row("🔎 PM Search", s.get("pm_search_enabled"), "pm_search_enabled"),
              row("🆕 Movie Updates", s.get("movie_updates_enabled"), "movie_updates_enabled"),
              row("📩 Request System", s.get("request_system_enabled"), "request_system_enabled"),
              row("▶️ Streaming", s.get("streaming_enabled"), "streaming_enabled"),
              row("🔐 Verification", s.get("verification_enabled"), "verification_enabled"),
              row("📢 Force Subscribe", s.get("force_sub_enabled"), "force_sub_enabled"),
              row("🧹 Auto Delete", s.get("auto_delete_enabled"), "auto_delete_enabled"),
              [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "payments":
        text = "💳 <b>PAYMENT METHODS</b>\n━━━━━━━━━━━━━━━━━━\nOnly enabled methods will appear to users."
        kb = [row("💳 UPI", s.get("payment_upi_enabled"), "payment_upi_enabled"), row("🪙 Crypto", s.get("payment_crypto_enabled"), "payment_crypto_enabled"), row("⭐ Telegram Stars", s.get("payment_stars_enabled"), "payment_stars_enabled"), [InlineKeyboardButton("💎 Manage Plans", callback_data="adm_plans")], [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "channels":
        def fmt(v): return "Not set" if not v else f"<code>{v}</code>"
        text = ("📡 <b>CHANNEL SETTINGS</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"📩 Request: {fmt(s.get('request_channel'))}\n"
                f"📣 Movie Updates: {fmt(s.get('movie_update_channel'))}\n"
                f"💾 Backup/File: {fmt(s.get('backup_channel'))}\n"
                f"🔐 Auth: {fmt(s.get('auth_channels'))}\n"
                f"📝 Logs: {fmt(s.get('log_channel'))}\n"
                f"💎 Premium Logs: {fmt(s.get('premium_logs'))}\n\n"
                f"🔐 Auth system: <b>{yn(s.get('auth_enabled'))}</b>\n"
                f"💾 Backup: <b>{yn(s.get('backup_enabled'))}</b>\n"
                f"📝 Logging: <b>{yn(s.get('logging_enabled'))}</b>\n\n"
                "To set a channel, forward any message from that channel to the bot.")
        kb = [[InlineKeyboardButton("📩 Set Request Channel", callback_data="adm_setchannel:request_channel")], [InlineKeyboardButton("📣 Set Movie Update", callback_data="adm_setchannel:movie_update_channel")], [InlineKeyboardButton("💾 Set Backup/File", callback_data="adm_setchannel:backup_channel")], [InlineKeyboardButton("🔐 Set Auth Channel", callback_data="adm_setchannel:auth_channels")], [InlineKeyboardButton("📝 Set Log Channel", callback_data="adm_setchannel:log_channel")], [InlineKeyboardButton("💎 Set Premium Logs", callback_data="adm_setchannel:premium_logs")], [InlineKeyboardButton("🔐 Auth ON/OFF", callback_data="adm_toggle:auth_enabled"), InlineKeyboardButton("💾 Backup ON/OFF", callback_data="adm_toggle:backup_enabled")], [InlineKeyboardButton("📝 Logging ON/OFF", callback_data="adm_toggle:logging_enabled")], [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "referral":
        reward = int(s.get("referral_reward_points", 5)); threshold = int(s.get("referral_redeem_points", 20)); days = int(s.get("referral_redeem_days", 10))
        text = ("🤝 <b>REFERRAL SYSTEM</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"Status: <b>{yn(s.get('referral_enabled'))}</b>\n"
                f"🎁 Reward: <b>{reward} points / qualified referral</b>\n"
                f"🎟️ Redeem: <b>{threshold} points → {days} days Premium</b>\n"
                f"⚡ Qualification: <b>first successful search</b>\n\n"
                "Points are Premium/Reward credit, not cash.")
        kb = [[InlineKeyboardButton(f"🤝 Referral: {yn(s.get('referral_enabled'))}", callback_data="adm_toggle:referral_enabled")], [InlineKeyboardButton("➕ Reward Points", callback_data="adm_ref_reward")], [InlineKeyboardButton("🎟️ Redeem Rule", callback_data="adm_ref_redeem")], [InlineKeyboardButton("📊 Referral Stats", callback_data="adm_ref_stats")], [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "catalogue":
        states = await get_index_state()
        text = f"🎬 <b>CATALOGUE & INDEXING</b>\n━━━━━━━━━━━━━━━━━━\n📚 Files: <b>{await _count_files()}</b>\n📌 Saved index states: <b>{len(states)}</b>\n\nUse <code>/setskip NUMBER</code> to choose a manual start point. After a successful indexing run, the channel's last processed message ID is saved automatically."
        kb = [[InlineKeyboardButton("⏭️ Set Skip Help", callback_data="adm_skiphelp")], [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "requests":
        count = await mdb.db["movie_requests"].count_documents({"status": "pending"})
        text = f"📩 <b>REQUEST CENTER</b>\n━━━━━━━━━━━━━━━━━━\n⏳ Pending: <b>{count}</b>\n\nRequests continue to use the existing moderation/reply flow."
        kb = [[InlineKeyboardButton("🔄 Refresh", callback_data="adm_page:requests")], [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "users":
        text = f"👥 <b>USER CENTER</b>\n━━━━━━━━━━━━━━━━━━\nTotal users: <b>{await db.total_users_count()}</b>\nPremium: <b>{await db.all_premium_users()}</b>\n\nUse existing admin commands for detailed user actions."
        kb = [[InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    elif key == "broadcast":
        text = "📢 <b>BROADCAST CENTER</b>\n━━━━━━━━━━━━━━━━━━\nUse <code>/broadcast</code> for users and <code>/grp_broadcast</code> for connected groups. Scheduled broadcast remains available via <code>/schedule_broadcast</code>."
        kb = [[InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    else:
        text = "🛡️ <b>SECURITY & LOGS</b>\n━━━━━━━━━━━━━━━━━━\nAdmin-only panel. Secrets remain in environment variables. Runtime changes are stored in MongoDB."
        kb = [[InlineKeyboardButton("📜 Admin Activity", callback_data="adm_logs")], [InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]
    return text, InlineKeyboardMarkup(kb)

@Client.on_message(filters.command("admin") & filters.user(ADMINS))
async def admin_panel(client, message):
    await ensure_settings(); await ensure_indexes()
    await log_admin_action(message.from_user.id, "open_panel")
    await message.reply_text(await dashboard_text(), reply_markup=dashboard_kb(), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^adm_"))
async def admin_callbacks(client, query):
    if query.from_user.id not in ADMINS:
        return await query.answer("Admins only.", show_alert=True)
    data = query.data
    if data == "adm_home" or data == "adm_refresh":
        return await query.message.edit_text(await dashboard_text(), reply_markup=dashboard_kb(), parse_mode=enums.ParseMode.HTML)
    if data.startswith("adm_page:"):
        text, kb = await render_page(data.split(":",1)[1]); return await query.message.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    if data.startswith("adm_toggle:"):
        key = data.split(":",1)[1]; old = bool(await get_setting(key, False)); await set_setting(key, not old, query.from_user.id)
        if key == "pm_search_enabled":
            try: await db.update_pm_search_status(client.me.id, not old)
            except Exception: pass
        if key == "movie_updates_enabled":
            try: await db.update_movie_update_status(client.me.id, not old)
            except Exception: pass
        await query.answer(f"{key.replace('_',' ').title()}: {'ON' if not old else 'OFF'}")
        if key in {"maintenance_mode","payment_upi_enabled","payment_crypto_enabled","payment_stars_enabled","referral_enabled"}:
            # Keep payment handlers synchronized via DB on their next call.
            pass
        page = "controls" if key in {"maintenance_mode","shortener_enabled","content_forwarding_enabled","pm_search_enabled","movie_updates_enabled","request_system_enabled","streaming_enabled","verification_enabled","force_sub_enabled","auto_delete_enabled"} else ("payments" if key.startswith("payment_") else ("channels" if key in {"auth_enabled","backup_enabled","logging_enabled"} else "referral"))
        text, kb = await render_page(page); return await query.message.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    if data.startswith("adm_setchannel:"):
        target = data.split(":",1)[1]
        pending_channels[query.from_user.id] = target
        return await query.answer(f"Forward a message from the {target.replace('_',' ')} channel to me.", show_alert=True)
    if data == "adm_skiphelp": return await query.answer("/setskip 1000 — manual start. Successful indexing now saves the last processed message ID automatically.", show_alert=True)
    if data == "adm_ref_stats":
        text = await dashboard_text(); return await query.answer("Referral statistics are available in each user's Refer & Earn screen.", show_alert=True)
    if data == "adm_ref_reward":
        return await query.answer("Default: 5 points per qualified referral. Change with /refreward POINTS.", show_alert=True)
    if data == "adm_ref_redeem":
        return await query.answer("Default: 20 points → 10 days Premium. Change with /refredeem POINTS DAYS.", show_alert=True)
    if data == "adm_plans":
        return await query.answer("Premium plans remain managed by payment_system.py; this panel controls payment-method availability.", show_alert=True)
    if data == "adm_logs":
        docs = await mdb.db["admin_activity_logs"].find({}).sort("created_at", -1).to_list(length=10)
        lines = ["📜 <b>RECENT ADMIN ACTIVITY</b>", "━━━━━━━━━━━━━━━━━━"] + [f"• {d.get('action')} — {d.get('admin_id')}" for d in docs]
        return await query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="adm_home")]]), parse_mode=enums.ParseMode.HTML)

pending_channels = {}

@Client.on_message(filters.private & filters.forwarded & filters.user(ADMINS), group=10)
async def admin_channel_forward(client, message):
    target = pending_channels.pop(message.from_user.id, None)
    if not target or not message.forward_from_chat:
        return
    chat_id = int(message.forward_from_chat.id)
    # Verify bot can access the channel and, for operational channels, report permission status.
    try:
        chat = await client.get_chat(chat_id)
        bot_member = await client.get_chat_member(chat_id, client.me.id)
        allowed_status = {enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.MEMBER}
        if bot_member.status not in allowed_status:
            raise RuntimeError("Bot is not a member of this channel/chat.")
        if target in {"request_channel", "movie_update_channel", "log_channel", "premium_logs", "backup_channel"} and bot_member.status == enums.ChatMemberStatus.MEMBER:
            raise RuntimeError("Bot must be an administrator to post in this channel.")
        await set_setting(target, [chat_id] if target == "auth_channels" else chat_id, message.from_user.id)
        if target == "movie_update_channel":
            link = f"https://t.me/{chat.username}" if getattr(chat, "username", None) else (getattr(chat, "invite_link", None) or "")
            if link:
                await set_setting("movie_update_channel_link", link, message.from_user.id)
        await message.reply_text(f"✅ <b>{target.replace('_',' ').title()} set successfully.</b>\n\n📡 {chat.title}\n🆔 <code>{chat_id}</code>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ Could not set channel. Make sure the bot is a member/admin there.\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("refreward") & filters.user(ADMINS))
async def refreward(client, message):
    if len(message.command) != 2 or not message.command[1].isdigit(): return await message.reply_text("Usage: /refreward POINTS")
    await set_setting("referral_reward_points", int(message.command[1]), message.from_user.id); await message.reply_text(f"✅ Referral reward set to {message.command[1]} points.")

@Client.on_message(filters.command("refredeem") & filters.user(ADMINS))
async def refredeem(client, message):
    if len(message.command) != 3 or not all(x.isdigit() for x in message.command[1:]): return await message.reply_text("Usage: /refredeem POINTS DAYS")
    await set_setting("referral_redeem_points", int(message.command[1]), message.from_user.id); await set_setting("referral_redeem_days", int(message.command[2]), message.from_user.id); await message.reply_text(f"✅ {message.command[1]} points = {message.command[2]} days Premium.")

async def sync_bot_profile(bot):
    await ensure_settings(); await ensure_indexes()
    user_cmds = [BotCommand("start", "Start the bot"), BotCommand("search", "Search movies & series"), BotCommand("premium", "View premium plans"), BotCommand("myplan", "Check premium status"), BotCommand("request", "Request a movie"), BotCommand("refer", "Refer & earn Premium credit"), BotCommand("help", "Get help"), BotCommand("about", "About the bot")]
    admin_cmds = user_cmds + [BotCommand("admin", "Open Admin Panel"), BotCommand("stats", "Bot statistics"), BotCommand("broadcast", "Broadcast to users"), BotCommand("grp_broadcast", "Broadcast to groups"), BotCommand("add_premium", "Add Premium"), BotCommand("remove_premium", "Remove Premium"), BotCommand("premium_users", "List Premium users"), BotCommand("deletefiles", "Delete indexed files"), BotCommand("restart", "Restart the bot"), BotCommand("logs", "View logs")]
    try: await bot.set_bot_commands(user_cmds)
    except Exception: pass
    try: await bot.set_my_short_description("🎬 Search • Download • Stream • Premium • Requests • Referral Rewards")
    except Exception: pass
    try: await bot.set_my_description("🎬 Movie & Series Bot\n\n🔎 Search your favourite movies and series\n⬇️ Fast Telegram delivery\n▶️ Online streaming\n💎 Premium plans\n💳 UPI • Crypto • Telegram Stars\n📩 Movie requests\n🤝 Referral Premium credits\n📡 Latest movie updates")
    except Exception: pass
    for aid in ADMINS:
        try: await bot.set_bot_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=int(aid)))
        except Exception: pass

@Client.on_message(filters.incoming, group=-100)
async def maintenance_gate(client, message):
    try:
        if not await get_setting("maintenance_mode", False):
            return
        if message.from_user and message.from_user.id in ADMINS:
            return
        if message.chat and message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return
        text = "🛠️ <b>BOT IS UNDER MAINTENANCE</b>\n\nWe are updating the bot right now. Please try again shortly. 🙏"
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
        try: message.stop_propagation()
        except Exception: pass
    except Exception: pass
