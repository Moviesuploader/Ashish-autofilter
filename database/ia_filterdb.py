import logging
from struct import pack
import re
import base64
import hashlib
from datetime import datetime, timezone
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import CAPTION_LANGUAGES, DATABASE_URI, DATABASE_URI2, DATABASE_NAME, COLLECTION_NAME, USE_CAPTION_FILTER, MAX_B_TN, DEENDAYAL_MOVIE_UPDATE_CHANNEL, OWNERID
from utils import get_settings, save_group_settings, temp, get_status
from database.users_chats_db import add_name
from .Imdbposter import get_movie_details, fetch_image
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.admin_settings_db import get_setting

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
#---------------------------------------------------------
# Some basic variables needed
tempDict = {'indexDB': DATABASE_URI}

# Primary DB
client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

#secondary db
client2 = AsyncIOMotorClient(DATABASE_URI2)
db2 = client2[DATABASE_NAME]
instance2 = Instance.from_db(db2)


# Primary DB Model
@instance.register
class Media(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME

@instance2.register
class Media2(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME

async def choose_mediaDB():
    """This Function chooses which database to use based on the value of indexDB key in the dict tempDict."""
    global saveMedia
    if tempDict['indexDB'] == DATABASE_URI:
        logger.info("Using first db (Media)")
        saveMedia = Media
    else:
        logger.info("Using second db (Media2)")
        saveMedia = Media2

async def save_file(bot, media, update_message=None):
  """Save file in database"""
  global saveMedia
  file_id, file_ref = unpack_new_file_id(media.file_id)
  file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
  try:
    if saveMedia == Media2: 
        if await Media.count_documents({'file_id': file_id}, limit=1):
            logger.warning(f'{file_name} is already saved in primary database!')
            return False, 0
    file = saveMedia(
        file_id=file_id,
        file_ref=file_ref,
        file_name=file_name,
        file_size=media.file_size,
        file_type=media.file_type,
        mime_type=media.mime_type,
        caption=media.caption.html if media.caption else None,
    )
  except ValidationError:
    logger.exception('Error occurred while saving file in database')
    return False, 2
  else:
    try:
      await file.commit()
    except DuplicateKeyError:
      logger.warning(f'{getattr(media, "file_name", "NO_FILE")} is already saved in database')   
      return False, 0
    else:
        logger.info(f'{getattr(media, "file_name", "NO_FILE")} is saved to database')
        if await get_status(bot.me.id):
            # Publish only after the file is safely committed. send_msg() has an
            # atomic identity ledger, so 720p/1080p, repeated qualities and
            # duplicate season uploads do not create repeated update cards.
            try:
                await send_msg(bot, file.file_name, file.caption, file.file_size)
            except Exception:
                logger.exception("Movie update failed after successful indexing")
        return True, 1

async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=False):
    """For given query return (results, next_offset)"""
    if chat_id is not None:
        settings = await get_settings(int(chat_id))
        try:
            if settings['max_btn']:
                max_results = 10
            else:
                max_results = int(MAX_B_TN)
        except KeyError:
            await save_group_settings(int(chat_id), 'max_btn', False)
            settings = await get_settings(int(chat_id))
            if settings['max_btn']:
                max_results = 10
            else:
                max_results = int(MAX_B_TN)
    query = query.strip()
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_()]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []

    if USE_CAPTION_FILTER:
        filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        filter = {'file_name': regex}

    if file_type:
        filter['file_type'] = file_type

    total_results = ((await Media.count_documents(filter))+(await Media2.count_documents(filter)))

    # Robust catalogue fallback: users should be able to type the movie name
    # naturally. Indexed filenames often contain release tags, Unicode
    # punctuation, language/quality labels and season/episode markers.
    # When the legacy phrase regex misses, search significant title tokens as
    # plain substrings (case-insensitive) across both indexed collections.
    if total_results == 0 and query:
        normalized = re.sub(r"[._+\-\[\]{}()/:|]+", " ", query, flags=re.IGNORECASE)
        normalized = re.sub(r"\b(?:s|season)\s*0*(\d{1,2})\b", r"season \1", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b(?:e|ep|episode)\s*0*(\d{1,3})\b", r"episode \1", normalized, flags=re.IGNORECASE)
        stop = {
            "movie", "movies", "series", "full", "file", "download",
            "watch", "in", "with", "and", "please", "send", "link",
            "find", "give", "get", "season", "episode",
        }
        tokens = [
            t for t in re.findall(r"[\w]+", normalized.lower(), flags=re.UNICODE)
            if len(t) > 1 and t not in stop
        ]
        if tokens:
            # First require every meaningful title token. This handles natural
            # queries while avoiding matches based only on generic words.
            token_clauses = []
            for token in tokens[:12]:
                token_re = re.compile(re.escape(token), flags=re.IGNORECASE)
                fields = [{"file_name": token_re}]
                if USE_CAPTION_FILTER:
                    fields.append({"caption": token_re})
                token_clauses.append({"$or": fields})
            fallback_filter = {"$and": token_clauses}
            if file_type:
                fallback_filter["file_type"] = file_type
            total_results = (
                await Media.count_documents(fallback_filter)
                + await Media2.count_documents(fallback_filter)
            )
            if total_results:
                filter = fallback_filter
            else:
                # Catalogue-only last resort: use the strongest title token.
                # This is deliberately still restricted to indexed files and is
                # what prevents an already-indexed movie from becoming a false
                # "not found" merely because the release filename differs.
                strongest = max(tokens[:12], key=len)
                strong_re = re.compile(re.escape(strongest), flags=re.IGNORECASE)
                strong_fields = [{"file_name": strong_re}]
                if USE_CAPTION_FILTER:
                    strong_fields.append({"caption": strong_re})
                strong_filter = {"$or": strong_fields}
                if file_type:
                    strong_filter["file_type"] = file_type
                strong_total = (
                    await Media.count_documents(strong_filter)
                    + await Media2.count_documents(strong_filter)
                )
                if strong_total:
                    filter = strong_filter
                    total_results = strong_total

    #verifies max_results is an even number or not
    if max_results%2 != 0: 
        logger.info(f"Since max_results is an odd number ({max_results}), bot will use {max_results+1} as max_results to make it even.")
        max_results += 1

    cursor = Media.find(filter)
    cursor2 = Media2.find(filter)

    cursor.sort('$natural', -1)
    cursor2.sort('$natural', -1)

    cursor2.skip(offset).limit(max_results)

    fileList2 = await cursor2.to_list(length=max_results)
    if len(fileList2)<max_results:
        next_offset = offset+len(fileList2)
        cursorSkipper = (next_offset-(await Media2.count_documents(filter)))
        cursor.skip(cursorSkipper if cursorSkipper>=0 else 0).limit(max_results-len(fileList2))
        fileList1 = await cursor.to_list(length=(max_results-len(fileList2)))
        files = fileList2+fileList1
        next_offset = next_offset + len(fileList1)
    else:
        files = fileList2
        next_offset = offset + max_results
    if next_offset >= total_results:
        next_offset = ''
    return files, next_offset, total_results


async def get_bad_files(query, file_type=None, filter=False):
    """For given query return (results, next_offset)"""
    query = query.strip()
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_()]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []

    if USE_CAPTION_FILTER:
        filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        filter = {'file_name': regex}

    if file_type:
        filter['file_type'] = file_type

    cursor = Media.find(filter)
    cursor2 = Media2.find(filter)

    cursor.sort('$natural', -1)
    cursor2.sort('$natural', -1)

    files = ((await cursor2.to_list(length=(await Media2.count_documents(filter))))+(await cursor.to_list(length=(await Media.count_documents(filter)))))

    total_results = len(files)

    return files, total_results

async def get_file_details(query):
    filter = {'file_id': query}
    cursor = Media.find(filter)
    filedetails = await cursor.to_list(length=1)
    if not filedetails:
        cursor2 = Media2.find(filter)
        filedetails = await cursor2.to_list(length=1)
    return filedetails


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0

    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0

            r += bytes([i])

    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")

def unpack_new_file_id(new_file_id):
    """Return file_id, file_ref"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref


async def _movie_update_candidates(filename, caption):
    """Build compact, IMDb-friendly title candidates from noisy upload names."""
    raw = f"{filename or ''} {caption or ''}"
    raw = re.sub(r'\.(mp4|mkv|avi|mov|webm|m4v|mp3|flac|pdf)$', '', raw, flags=re.I)
    raw = re.sub(r'\[.*?\]|\(.*?\)', ' ', raw)
    raw = re.sub(r'@\S+|www\.\S+', ' ', raw, flags=re.I)
    raw = raw.replace('_', ' ').replace('.', ' ')
    raw = re.sub(r'\b(?:2160p|1440p|1080p|720p|480p|360p|4k|8k|web[- ]?dl|web[- ]?rip|bluray|brrip|bdrip|hdrip|hdtv|camrip|hdcam|dvdscr|dvdrip|hdts|hdtc)\b', ' ', raw, flags=re.I)
    raw = re.sub(r'\b(?:x264|x265|h264|h265|hevc|av1|aac|ddp?\d(?:\.\d)?|5\.1|2\.0|10bit|proper|repack|uncut|sample)\b', ' ', raw, flags=re.I)
    raw = re.sub(r'\b(?:480p|720p|1080p|2160p)\b', ' ', raw, flags=re.I)
    raw = re.sub(r'\s+', ' ', raw).strip(' -_')
    year_match = re.search(r'\b(19|20)\d{2}\b', raw)
    year = year_match.group(0) if year_match else 'N/A'
    # Prefer the series/movie identity over episode-specific noise.
    base = re.sub(r'\b(?:episode|ep|e)\s*[-_. ]?\d+\b.*$', '', raw, flags=re.I).strip(' -_')
    base = re.sub(r'\b(?:day|part|pt)\s*[-_. ]?\d+\b.*$', '', base, flags=re.I).strip(' -_')
    season_match = re.search(r'\b(?:s|season)\s*[-_. ]?0*(\d{1,2})\b', raw, flags=re.I)
    if season_match:
        season_label = f"Season {int(season_match.group(1))}"
        # Keep the series name + season, but drop episode/day suffixes.
        base = re.sub(r'\b(?:episode|ep|e)\s*[-_. ]?\d+\b.*$', '', base, flags=re.I).strip(' -_')
        base = re.sub(r'\b(?:day|part|pt)\s*[-_. ]?\d+\b.*$', '', base, flags=re.I).strip(' -_')
        if season_label.lower() not in base.lower():
            # Search both with and without the season marker.
            season_base = f"{base} {season_label}".strip()
        else:
            season_base = base
    else:
        season_base = base
    candidates = []
    # For episodic uploads, search the clean series/movie title first.
    # A query such as "Bigg Boss Season 20" is often less reliable on IMDb
    # than "Bigg Boss", while the season marker is still retained for our
    # update-channel deduplication identity.
    clean_base = re.sub(r'\b(?:s|season)\s*[-_. ]?0*\d{1,2}\b', ' ', base, flags=re.I)
    clean_base = re.sub(r'\s+', ' ', clean_base).strip(' -_')
    candidate_order = (clean_base, season_base, base, raw) if season_match else (base, raw)
    for q in candidate_order:
        q = re.sub(r'\s+', ' ', q).strip(' -_')
        if q and q.lower() not in {x.lower() for x in candidates}:
            candidates.append(q)
    return candidates[:4], year, season_match.group(1) if season_match else ''


async def send_msg(bot, filename, caption, file_size=0, status="⏳ Movie indexed & uploaded successfully."):
    """Publish one final update per movie/series identity.

    The deduplication claim is made before the optional IMDb lookup so repeated
    qualities/episodes do not repeatedly hit IMDb or flood the update channel.
    A failed publish releases the claim, allowing a later indexing run to retry.
    """
    update_key = None
    try:
        if not await get_setting("movie_updates_enabled", True):
            return None
        channel = await get_setting("movie_update_channel", DEENDAYAL_MOVIE_UPDATE_CHANNEL)
        if not channel:
            return None

        filename = re.sub(r'\(\@\S+\)|\[\@\S+\]|\b@\S+|\bwww\.\S+', '', filename or '').strip()
        caption = re.sub(r'\(\@\S+\)|\[\@\S+\]|\b@\S+|\bwww\.\S+', '', caption or '').strip()
        combined = f"{caption} {filename}"
        year_match = re.search(r"\b(19|20)\d{2}\b", caption) or re.search(r"\b(19|20)\d{2}\b", filename)
        year = year_match.group(0) if year_match else "N/A"
        season = re.search(r"(?i)(?:s|season)0*(\d{1,2})", combined)
        season_text = f"S{int(season.group(1)):02d}" if season else ""
        episode_match = re.search(r'\b(?:episode|ep|e)\s*[-_. ]?(\d{1,3})\b', combined, flags=re.I)
        episode_text = f"E{int(episode_match.group(1)):02d}" if episode_match else ""

        candidates, _, _ = await _movie_update_candidates(filename, caption)
        fallback_title = candidates[0] if candidates else re.sub(r'\s+', ' ', filename).strip()
        fallback_title = re.sub(r'\s+', ' ', fallback_title).strip() or "Movie"

        # Claim the logical movie/series identity before doing any network IMDb
        # work. For a season, all episodes and qualities share one identity.
        # For movies, qualities/languages/sizes also share one identity.
        identity = f"{fallback_title.lower()}|{year}|{season_text}" if season_text else f"{fallback_title.lower()}|{year}"
        update_key = hashlib.sha1(re.sub(r'[^a-z0-9|]+', '', identity).encode()).hexdigest()
        update_col = db["movie_update_posts"]
        try:
            await update_col.insert_one({
                "_id": update_key,
                "status": "publishing",
                "title": fallback_title,
                "year": year,
                "season": season_text,
                "episode": episode_text,
                "created_at": datetime.now(timezone.utc),
            })
        except DuplicateKeyError:
            return None

        imdb = None
        # IMDb/Cinemagoer performs blocking network calls internally. It is
        # wrapped by get_movie_details so the bot event loop remains responsive.
        for candidate in candidates:
            try:
                query = f"{candidate} {year}" if year != "N/A" else candidate
                imdb = await get_movie_details(query)
                if imdb:
                    break
            except Exception:
                logger.debug("IMDb lookup failed for candidate %s", candidate, exc_info=True)

        title = imdb.get("title") if imdb else fallback_title
        title = re.sub(r'\s+', ' ', str(title)).strip() or fallback_title
        rating = imdb.get("rating") if imdb else "N/A"
        genres = imdb.get("genres") if imdb else "N/A"
        plot = imdb.get("plot") if imdb else ""
        if plot and len(plot) > 260:
            plot = plot[:257] + "..."

        size_text = "N/A"
        if file_size:
            size = float(file_size)
            units = ["B", "KB", "MB", "GB", "TB"]
            i = 0
            while size >= 1024 and i < len(units) - 1:
                size /= 1024
                i += 1
            size_text = f"{size:.2f} {units[i]}"

        quality_terms = ["2160p", "1440p", "1080p", "720p", "480p", "360p", "WEB-DL", "WEBRip", "BluRay", "HDRip", "HDTV", "HDCAM", "CAMRip", "DVDscr", "DVDRip", "HDTS", "HDTC"]
        quality = next((q for q in quality_terms if q.lower() in combined.lower()), "N/A")
        language = ""
        for lang in CAPTION_LANGUAGES:
            if lang and lang.lower() in combined.lower() and lang.lower() not in language.lower():
                language += (", " if language else "") + lang
        language = language or "N/A"

        season_line = f"📺 Season: <b>{season_text}</b>" if season_text else ""
        episode_line = f"🎬 Episode: <b>{episode_text}</b>" if episode_text else ""
        extra = "\n".join(x for x in (season_line, episode_line) if x)
        if extra:
            extra += "\n"
        plot_line = f"\n📝 {plot}" if plot else ""
        text = (
            f"🎬 <b>{title}</b>" + (f" <b>({year})</b>" if year != "N/A" else "") + "\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⭐ IMDb: <b>{rating}</b>/10\n"
            f"🎭 Genre: <b>{genres or 'N/A'}</b>\n"
            f"🎞️ Quality: <b>{quality}</b>\n"
            f"🌐 Language: <b>{language}</b>\n"
            f"💾 Size: <b>{size_text}</b>\n"
            f"{extra}\n{status}{plot_line}"
        )

        # Telegram start parameters are short. Keep the slug comfortably under
        # the Bot API limit while retaining the resolved title/year for search.
        search_slug = re.sub(
            r'[^a-zA-Z0-9]+', '-',
            f"{title} {year if year != 'N/A' else ''}"
        ).strip('-').lower()[:54].strip('-')
        bot_username = getattr(temp, "U_NAME", "") or ""
        btn = [[InlineKeyboardButton(
            "🎬 GET THIS MOVIE",
            url=f"https://t.me/{bot_username}?start=getfile-{search_slug}"
        )]] if bot_username and search_slug else []
        markup = InlineKeyboardMarkup(btn) if btn else None

        poster_sent = False
        if imdb and imdb.get("poster_url"):
            try:
                poster = await fetch_image(imdb["poster_url"])
                if poster:
                    await bot.send_photo(chat_id=channel, photo=poster, caption=text, reply_markup=markup)
                    poster_sent = True
            except Exception:
                logger.warning("Movie poster upload failed for %s; falling back to text", title, exc_info=True)

        if not poster_sent:
            await bot.send_message(
                chat_id=channel,
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )

        await update_col.update_one(
            {"_id": update_key},
            {"$set": {
                "status": "sent",
                "title": title,
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        return True
    except Exception:
        logger.exception("Movie update publish failed")
        if update_key:
            try:
                await db["movie_update_posts"].delete_one({"_id": update_key, "status": "publishing"})
            except Exception:
                logger.debug("Failed to release movie update claim", exc_info=True)
        return None

async def get_qualities(text, qualities: list):
    """Get all Quality from text"""
    quality = []
    for q in qualities:
        if q in text:
            quality.append(q)
    quality = ", ".join(quality)
    return quality[:-2] if quality.endswith(", ") else quality






