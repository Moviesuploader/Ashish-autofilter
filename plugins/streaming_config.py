"""Streaming configuration helpers.

All values are environment-driven so the streaming layer remains portable
between local development and Koyeb deployments.
"""
from os import environ


def env_bool(name, default=False):
    value = environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


STREAM_AUTO_FAILOVER = env_bool("STREAM_AUTO_FAILOVER", True)
STREAM_ENABLE_DOWNLOAD = env_bool("STREAM_ENABLE_DOWNLOAD", True)
STREAM_PRELOAD = environ.get("STREAM_PRELOAD", "metadata")
STREAM_MAX_RETRIES = max(0, int(environ.get("STREAM_MAX_RETRIES", "2")))
STREAM_RETRY_DELAY = max(0.1, float(environ.get("STREAM_RETRY_DELAY", "0.75")))
