"""
Deendayal Movie Bot — Final UI System
Telegram-native UI helpers. Business logic remains in existing handlers.
"""

HOME = "🏠 Home"
BACK = "🔙 Back"
CLOSE = "✖️ Close"
SEARCH = "🔎 Search Movies"
LATEST = "🆕 Latest Movies"
PREMIUM = "⭐ Premium"
REQUEST = "📩 Request Movie"
MY_FILES = "📚 My Files"
HELP = "❓ Help"
ABOUT = "ℹ️ About"
SUPPORT = "💬 Support"
SHARE = "📤 Share Bot"

NAV_LABELS = {
    SEARCH, LATEST, PREMIUM, REQUEST, MY_FILES, HELP, ABOUT, SUPPORT, HOME, BACK, CLOSE,
    "🔙 Back to Menu",
}

def home_text(name="there"):
    return (
        f"🎬 <b>Welcome, {name}!</b>\n\n"
        "🍿 <b>Your movie hub is ready.</b>\n"
        "Search movies & series, choose your quality and get your file fast.\n\n"
        "⚡ <i>Simple • Fast • Organized</i>"
    )

def search_text():
    return (
        "🔎 <b>Search Movies & Series</b>\n\n"
        "Send me the <b>movie or series name</b> you want to find.\n"
        "<i>Example: Avengers Endgame</i>"
    )

def movie_card(title, year="", rating="", genre="", language="", plot=""):
    meta = " • ".join(str(x) for x in (year, rating, genre, language) if x)
    text = f"🎬 <b>{title}</b>"
    if meta:
        text += f"\n\n📌 {meta}"
    if plot:
        clean = str(plot).strip()
        if len(clean) > 350:
            clean = clean[:347] + "..."
        text += f"\n\n📝 {clean}"
    return text

def result_header(query, count=None):
    found = f"\n📦 <b>{count}</b> result(s) found" if count is not None else ""
    return f"🔎 <b>Results for:</b> <i>{query}</i>{found}"

def navigation(back=True, home=True, close=False):
    row = []
    if back:
        row.append(BACK)
    if home:
        row.append(HOME)
    if close:
        row.append(CLOSE)
    return row


def home_caption(name, greeting, bot_name):
    return (
        f"<b>🎬 {bot_name}</b>\n"
        f"<i>Your personal movie & series hub</i>\n\n"
        f"{greeting}, <b>{name}</b> 👋\n\n"
        "🔎 <b>Search instantly</b> for movies & series\n"
        "🎞️ Browse available qualities & languages\n"
        "⭐ Unlock a smoother ad-free experience\n\n"
        "<b>🍿 What are you watching today?</b>"
    )

def home_keyboard():
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(SEARCH, callback_data="ui_search")],
        [InlineKeyboardButton(LATEST, callback_data="topsearch"),
         InlineKeyboardButton(PREMIUM, callback_data="premium_info")],
        [InlineKeyboardButton(REQUEST, callback_data="ui_request"),
         InlineKeyboardButton(SUPPORT, callback_data="channels")],
        [InlineKeyboardButton(HELP, callback_data="ui_help"),
         InlineKeyboardButton(ABOUT, callback_data="ui_about")],
        [InlineKeyboardButton(SHARE, switch_inline_query="")],
    ])

def inner_keyboard(*, back="ui_home", home="ui_home"):
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    if back and home:
        rows.append([InlineKeyboardButton(BACK, callback_data=back),
                     InlineKeyboardButton(HOME, callback_data=home)])
    elif back:
        rows.append([InlineKeyboardButton(BACK, callback_data=back)])
    elif home:
        rows.append([InlineKeyboardButton(HOME, callback_data=home)])
    return InlineKeyboardMarkup(rows)

def result_nav():
    from pyrogram.types import InlineKeyboardButton
    return [InlineKeyboardButton(BACK, callback_data="ui_home"),
            InlineKeyboardButton(HOME, callback_data="ui_home")]

def reply_keyboard():
    """Persistent PM navigation keyboard."""
    from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(SEARCH)],
            [KeyboardButton(LATEST), KeyboardButton(PREMIUM)],
            [KeyboardButton(REQUEST), KeyboardButton(MY_FILES)],
            [KeyboardButton(HELP), KeyboardButton(ABOUT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        placeholder="Choose an option…",
    )
