import sys
import glob
import importlib
from pathlib import Path
from pyrogram import Client, idle, __version__
from pyrogram.errors import FloodWait
from pyrogram.raw.all import layer
import logging
import logging.config
import time
import asyncio
from datetime import date, datetime
import pytz
from aiohttp import web

from database.ia_filterdb import Media, Media2, choose_mediaDB, tempDict, db as clientDB
from database.users_chats_db import db
from info import *
from utils import temp
from Script import script
from plugins import web_server, check_expired_premium
from Deendayal_botz.Bot import DeendayalBot
from Deendayal_botz.util.keepalive import ping_server
from Deendayal_botz.Bot.clients import initialize_clients

logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logging.getLogger("aiohttp.web").setLevel(logging.ERROR)

botStartTime = time.time()
ppath = "plugins/*.py"
files = glob.glob(ppath)

async def _start_health_server():
    """Start the HTTP health endpoint before Telegram authorization.

    This keeps Koyeb health checks green even when Telegram asks the bot to
    wait before ImportBotAuthorization can be retried.
    """
    app = web.AppRunner(await web_server())
    await app.setup()
    bind_address = "0.0.0.0"
    await web.TCPSite(app, bind_address, PORT).start()
    logging.info("Health server listening on %s:%s", bind_address, PORT)
    return app


async def _safe_start_bot(client):
    """Authorize once at a time and obey Telegram FLOOD_WAIT without crashing.

    A process crash during ImportBotAuthorization makes platforms such as
    Koyeb restart the container, which immediately retries authorization and
    can extend the flood wait.  Staying alive and sleeping is the safe path.
    """
    while True:
        try:
            await client.start()
            return
        except FloodWait as e:
            wait_seconds = max(1, int(getattr(e, "value", 0) or 0))
            # Small cushion prevents retrying on the exact Telegram boundary.
            wait_seconds += 3
            logging.warning(
                "Telegram FLOOD_WAIT during bot authorization. Waiting %s seconds; "
                "the health server will remain online and authorization will retry once.",
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)


async def Deendayal_start():
    print('\n')
    print('\nInitalizing Deendayal_Botz')
    health_runner = await _start_health_server()
    try:
        await _safe_start_bot(DeendayalBot)
    except Exception:
        await health_runner.cleanup()
        raise
    bot_info = await DeendayalBot.get_me()
    DeendayalBot.username = bot_info.username
    await initialize_clients()
    for name in files:
        with open(name) as a:
            patt = Path(a.name)
            plugin_name = patt.stem.replace(".py", "")
            plugins_dir = Path(f"plugins/{plugin_name}.py")
            import_path = "plugins.{}".format(plugin_name)
            spec = importlib.util.spec_from_file_location(import_path, plugins_dir)
            load = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(load)
            sys.modules["plugins." + plugin_name] = load
            print("Deendayal dhakad Imported => " + plugin_name)
    try:
        from database.admin_settings_db import ensure_settings, get_setting, set_setting
        await ensure_settings()
        from plugins.admin_panel import sync_bot_profile
        await sync_bot_profile(DeendayalBot)
        # Seed runtime channel settings from ENV only when the admin panel has not set them yet.
        for _key, _value in (("movie_update_channel", DEENDAYAL_MOVIE_UPDATE_CHANNEL), ("log_channel", LOG_CHANNEL), ("premium_logs", PREMIUM_LOGS), ("backup_channel", FILE_STORE_CHANNEL[0] if FILE_STORE_CHANNEL else None), ("request_channel", REQST_CHANNEL)):
            if _value and not await get_setting(_key):
                await set_setting(_key, _value)
        if DEENDAYAL_MOVIE_UPDATE_CHANNEL_LNK and not await get_setting("movie_update_channel_link"):
            await set_setting("movie_update_channel_link", DEENDAYAL_MOVIE_UPDATE_CHANNEL_LNK)
    except Exception as e:
        logging.exception("Admin runtime initialization failed: %s", e)
    try:
        from plugins.payment_system import ensure_payment_indexes
        await ensure_payment_indexes()
    except Exception as e:
        logging.exception("Payment index initialization failed: %s", e)
        raise
    if ON_HEROKU:
        asyncio.create_task(ping_server()) 
    b_users, b_chats = await db.get_banned()
    temp.BANNED_USERS = b_users
    temp.BANNED_CHATS = b_chats
    await Media.ensure_indexes()
    await Media2.ensure_indexes()
    stats = await clientDB.command('dbStats')
    free_dbSize = round(512-((stats['dataSize']/(1024*1024))+(stats['indexSize']/(1024*1024))), 2)
    if DATABASE_URI2 and free_dbSize<62: #if the primary db have less than 62MB left, use second DB.
        tempDict["indexDB"] = DATABASE_URI2
        logging.info(f"Since Primary DB have only {free_dbSize} MB left, Secondary DB will be used to store datas.")
    elif not DATABASE_URI2:
        logging.error("Missing second DB URI !\n\nAdd SECONDDB_URI now !\n\nExiting...")
        exit()
    else:
        logging.info(f"Since primary DB have enough space ({free_dbSize}MB) left, It will be used for storing datas.")
    await choose_mediaDB()    
    me = await DeendayalBot.get_me()
    temp.ME = me.id
    temp.U_NAME = me.username
    temp.B_NAME = me.first_name
    temp.B_LINK = me.mention
    DeendayalBot.username = '@' + me.username
    DeendayalBot.loop.create_task(check_expired_premium(DeendayalBot))
    logging.info(f"{me.first_name} with Pyrogram v{__version__} (Layer {layer}) started on {me.username}.")
    logging.info(LOG_STR)
    logging.info(script.LOGO)
    tz = pytz.timezone('Asia/Kolkata')
    today = date.today()
    now = datetime.now(tz)
    time = now.strftime("%H:%M:%S %p")
    await DeendayalBot.send_message(chat_id=LOG_CHANNEL, text=script.RESTART_TXT.format(temp.B_LINK, today, time))
    try:
        await idle()
    finally:
        await health_runner.cleanup()
    
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(Deendayal_start())
    except KeyboardInterrupt:
        logging.info('Service Stopped Bye 👋')
