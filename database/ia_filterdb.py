import logging
from struct import pack
import re
import base64
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
            if update_message:
                try:
                    # The indexing layer owns the status message; keep its existing poster/buttons.
                    current_caption = update_message.caption.html if update_message.caption else ""
                    final_caption = current_caption.replace("⏳ <b>Indexing / Uploading...</b>", "✅ <b>Indexed & Uploaded Successfully</b>")
                    await update_message.edit_caption(final_caption)
                except Exception:
                    try: await send_msg(bot, file.file_name, file.caption, file.file_size)
                    except Exception: pass
            else:
                await send_msg(bot, file.file_name, file.caption, file.file_size)
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


async def send_msg(bot, filename, caption, file_size=0, status="⏳ Movie indexed & uploaded successfully."):
    """Publish a polished movie update to the runtime-configured update channel."""
    try:
        if not await get_setting("movie_updates_enabled", True):
            return
        channel = await get_setting("movie_update_channel", DEENDAYAL_MOVIE_UPDATE_CHANNEL)
        if not channel:
            return
        filename = re.sub(r'\(\@\S+\)|\[\@\S+\]|\b@\S+|\bwww\.\S+', '', filename).strip()
        caption = re.sub(r'\(\@\S+\)|\[\@\S+\]|\b@\S+|\bwww\.\S+', '', caption).strip()
        year_match = re.search(r"\b(19|20)\d{2}\b", caption) or re.search(r"\b(19|20)\d{2}\b", filename)
        year = year_match.group(0) if year_match else "N/A"
        pattern = r"(?i)(?:s|season)0*(\d{1,2})"
        season = re.search(pattern, caption) or re.search(pattern, filename)
        season_text = f"S{int(season.group(1)):02d}" if season else ""
        qualities = ["2160p","1440p","1080p","720p","480p","360p","WEB-DL","WEBRip","BluRay","HDRip","HDTV","HDCAM","CAMRip","DVDscr","DVDRip","HDTS","HDTC"]
        quality = next((q for q in qualities if q.lower() in caption.lower() or q.lower() in filename.lower()), "N/A")
        language = ""
        for lang in CAPTION_LANGUAGES:
            if lang and lang.lower() in caption.lower() and lang.lower() not in language.lower():
                language += (", " if language else "") + lang
        language = language or "N/A"
        clean_name = re.sub(r"[\(\)\[\]\{\}:;'\-!]", " ", filename)
        clean_name = re.sub(r"\s+", " ", clean_name).strip()
        if year != "N/A":
            clean_name = re.sub(r"\b(19|20)\d{2}\b", "", clean_name).strip(" -")
        size_text = "N/A"
        if file_size:
            size = float(file_size); units = ["B","KB","MB","GB","TB"]; i=0
            while size >= 1024 and i < len(units)-1: size/=1024; i+=1
            size_text = f"{size:.2f} {units[i]}"
        try:
            imdb = await get_movie_details(f"{clean_name} {year}" if year != "N/A" else clean_name)
        except Exception:
            imdb = None
        title = imdb.get("title") if imdb else clean_name
        rating = imdb.get("rating") if imdb else "N/A"
        genres = imdb.get("genres") if imdb else "N/A"
        plot = imdb.get("plot") if imdb else ""
        if plot and len(plot) > 300: plot = plot[:297] + "..."
        season_line = f"📺 Season: <b>{season_text}</b>\n" if season_text else ""
        plot_line = f"\n📝 {plot}" if plot else ""
        text = (f"🎬 <b>{title}</b> <b>({year})</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⭐ IMDb: <b>{rating}</b>/10\n"
                f"🎭 Genre: <b>{genres or 'N/A'}</b>\n"
                f"🎞️ Quality: <b>{quality}</b>\n"
                f"🌐 Language: <b>{language}</b>\n"
                f"💾 Size: <b>{size_text}</b>\n"
                f"{season_line}\n"
                f"{status}\n"
                f"{plot_line}")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{title}-{year}").strip("-")[:90]
        bot_username = getattr(temp, "U_NAME", "") or ""
        btn = [[InlineKeyboardButton("🎬 GET THIS MOVIE", url=f"https://t.me/{bot_username}?start=getfile-{slug}")]] if bot_username else []
        if imdb and imdb.get("poster_url"):
            await bot.send_photo(chat_id=channel, photo=imdb.get("poster_url"), caption=text, reply_markup=InlineKeyboardMarkup(btn) if btn else None)
        else:
            await bot.send_message(chat_id=channel, text=text, reply_markup=InlineKeyboardMarkup(btn) if btn else None, disable_web_page_preview=True)
    except Exception:
        logger.exception("Movie update publish failed")

async def get_qualities(text, qualities: list):
    """Get all Quality from text"""
    quality = []
    for q in qualities:
        if q in text:
            quality.append(q)
    quality = ", ".join(quality)
    return quality[:-2] if quality.endswith(", ") else quality






