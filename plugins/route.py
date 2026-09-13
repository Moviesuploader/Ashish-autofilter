from aiohttp import web
import re
import math
import logging
import secrets
import time
import mimetypes
from aiohttp.http_exceptions import BadStatusLine
from Deendayal_botz.Bot import multi_clients, work_loads, DeendayalBot
from Deendayal_botz.server.exceptions import FIleNotFound, InvalidHash
from Deendayal_botz.zzint import StartTime, __version__
from Deendayal_botz.util.custom_dl import ByteStreamer
from Deendayal_botz.util.time_format import get_readable_time
from Deendayal_botz.util.render_template import render_page
from info import *


routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("Deendayal_Botz")


@routes.get(r"/watch/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return web.Response(text=await render_page(id, secure_hash), content_type='text/html')
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))

@routes.get(r"/{path:\S+}", allow_head=True)
async def stream_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        match = re.search(r"^([a-zA-Z0-9_-]{6})(\d+)$", path)
        if match:
            secure_hash = match.group(1)
            id = int(match.group(2))
        else:
            id = int(re.search(r"(\d+)(?:\/\S+)?", path).group(1))
            secure_hash = request.rel_url.query.get("hash")
        return await media_streamer(request, id, secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FIleNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))

class_cache = {}

async def media_streamer(request: web.Request, id: int, secure_hash: str):
    range_header = request.headers.get("Range")

    # Pick the least-loaded Telegram client by default; allow the web player
    # to force a specific client when the current path is buffering.
    requested_server = request.rel_url.query.get("server", "auto")
    try:
        requested_index = int(requested_server) if requested_server != "auto" else None
    except (TypeError, ValueError):
        requested_index = None
    if requested_index in multi_clients and requested_index in work_loads:
        index = requested_index
    else:
        index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    
    if MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.remote}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logging.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(id)
    logging.debug("after calling get_file_properties")
    
    if file_id.unique_id[:6] != secure_hash:
        logging.debug(f"Invalid hash for message with ID {id}")
        raise InvalidHash
    
    file_size = file_id.file_size

    try:
        if range_header:
            raw = range_header.strip().lower()
            if not raw.startswith("bytes="):
                raise ValueError("invalid range unit")
            spec = raw[6:].split(",", 1)[0].strip()
            start_s, end_s = spec.split("-", 1)
            if not start_s:
                # Suffix range: bytes=-N
                suffix = int(end_s)
                if suffix <= 0:
                    raise ValueError("invalid suffix")
                from_bytes = max(file_size - suffix, 0)
                until_bytes = file_size - 1
            else:
                from_bytes = int(start_s)
                until_bytes = int(end_s) if end_s else file_size - 1
        else:
            from_bytes = request.http_range.start or 0
            until_bytes = (request.http_range.stop or file_size) - 1
    except (TypeError, ValueError):
        return web.Response(status=416, headers={"Content-Range": f"bytes */{file_size}"}, text="416: Range not satisfiable")

    if file_size <= 0 or (until_bytes >= file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    mime_type = file_id.mime_type
    file_name = file_id.file_name
    disposition = "attachment" if request.rel_url.query.get("download") == "1" else "inline"

    if mime_type:
        if not file_name:
            try:
                file_name = f"{secrets.token_hex(2)}.{mime_type.split('/')[1]}"
            except (IndexError, AttributeError):
                file_name = f"{secrets.token_hex(2)}.unknown"
    else:
        if file_name:
            mime_type = mimetypes.guess_type(file_id.file_name)
        else:
            mime_type = "application/octet-stream"
            file_name = f"{secrets.token_hex(2)}.unknown"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": f"{mime_type}",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=60",
            "X-Stream-Server": str(index),
        },
    )
