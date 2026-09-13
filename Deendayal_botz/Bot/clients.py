import asyncio
import logging
from info import *
from pyrogram import Client
from pyrogram.errors import FloodWait
from Deendayal_botz.util.config_parser import TokenParser
from . import multi_clients, work_loads, DeendayalBot


async def initialize_clients():
    multi_clients[0] = DeendayalBot
    work_loads[0] = 0
    all_tokens = TokenParser().parse_from_env()
    if not all_tokens:
        print("No additional clients found, using default client")
        return
    
    async def start_client(client_id, token):
        print(f"Starting - Client {client_id}")
        if client_id == len(all_tokens):
            await asyncio.sleep(2)
            print("This will take some time, please wait...")

        client = Client(
            name=str(client_id),
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=token,
            sleep_threshold=SLEEP_THRESHOLD,
            no_updates=True,
            in_memory=True
        )
        while True:
            try:
                await client.start()
                work_loads[client_id] = 0
                return client_id, client
            except FloodWait as e:
                wait_seconds = max(1, int(getattr(e, "value", 0) or 0)) + 3
                logging.warning(
                    "Telegram FLOOD_WAIT while authorizing extra Client %s. "
                    "Waiting %s seconds before one retry.",
                    client_id, wait_seconds
                )
                await asyncio.sleep(wait_seconds)
            except Exception:
                logging.error(f"Failed starting Client - {client_id} Error:", exc_info=True)
                return None
    
    results = await asyncio.gather(*[start_client(i, token) for i, token in all_tokens.items()])
    clients = [item for item in results if item is not None]
    multi_clients.update(dict(clients))
    if len(multi_clients) != 1:
        MULTI_CLIENT = True
        print("Multi-Client Mode Enabled")
    else:
        print("No additional clients were initialized, using default client")
