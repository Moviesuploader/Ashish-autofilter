"""Small non-invasive helpers for safer handler code."""


def clean_text(value, limit=4096):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
