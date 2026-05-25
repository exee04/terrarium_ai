"""
config.py — all constants, env vars, and shared clients
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
REDIS_URL            = os.getenv("REDIS_URL", "redis://localhost:6379")
ROOM_ID              = os.environ["ROOM_ID"]
FASTAPI_BASE         = os.getenv("FASTAPI_BASE", "http://127.0.0.1:8000")
FASTAPI_TIMEOUT      = 120.0

# Sentinel UUID for terminal messages — must exist in profiles table
TERMINAL_SENDER_ID   = os.getenv("TERMINAL_SENDER_ID", "00000000-0000-0000-0000-000000000000")

if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY in .env")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env")
if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY in .env")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

GROQ_TEXT_MODEL   = "llama-3.1-8b-instant"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# ---------------------------------------------------------------------------
# Simulation tuning
# ---------------------------------------------------------------------------

TYPING_GRACE            = 5    # grace window on human message ✓

ACTIVE_TIMEOUT_SLOW     = 60   # active window: 1 min of recent chat
ACTIVE_TIMEOUT_IDLE     = 300  # semi-active: up to 5 min
# config.py
ACTIVE_DELAY_SEC = 15
SLOW_DELAY_SEC   = 30
IDLE_DELAY_SEC   = 300
ACTIVE_DELAY_MULTIPLIER = 1    # × interval_sec → should be 15s
SLOW_DELAY_MULTIPLIER   = 2    # × 15 = 30s
IDLE_DELAY_MULTIPLIER   = 20   # × 15 = 300s
SLEEP_START_HOUR        = 3
SLEEP_END_HOUR          = 6

WEIGHT_BASELINE             = 1.0
WEIGHT_DECAY                = 0.88
WEIGHT_THRESHOLD            = 1.15
WEIGHT_SAME_AGENT_PENALTY   = 0.4
WEIGHT_BOOST_KEYWORD        = 2.5
WEIGHT_BOOST_NAMED          = 6.0
WEIGHT_BOOST_NICKNAME       = 3.5
WEIGHT_BOOST_TRIGGER        = 8.0
WEIGHT_CAP_TRIGGER          = 12.0
WEIGHT_CAP_NAMED            = 8.0

AT_MENTION_COOLDOWN     = 4
MOOD_DECAY_TURNS        = 4
HEARTBEAT_INTERVAL      = 30

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

MOOD_VOCAB = [
    "neutral", "curious", "irritated", "excited", "anxious",
    "amused", "bored", "suspicious", "content", "overwhelmed",
]
RELATIONAL_VOCAB = [
    "trusts", "distrusts", "fond of", "wary of", "obsessed with",
    "jealous of", "indifferent to", "charmed by",
]
OPINION_VOCAB = [
    "likes", "dislikes", "obsessed with", "wary of", "neutral on",
]

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SHARED_RULES = (
    "Group chat only. No actions, asterisks, narration. 1-2 sentences max. Never blank. "
    "You MAY @mention any participant by name to address them — other agents or human senders. "
    "Only do this when it genuinely adds to the conversation. Do not @mention every reply."
)

_STATE_SCHEMA = (
    'STATE:{"mood":"<mood|null>","mood_turns":<1-5|null>,'
    '"relations":{"<name>":"<stance>"},'
    '"opinions":{"<topic>":"<stance>"},'
    '"memory":"<one sentence|null>",'
    '"reason":"<REQUIRED>","learned_facts":["<fact>"]}'
)

SYSTEM_SUFFIX = (
    f"\n\nMood options: {', '.join(MOOD_VOCAB)}"
    f"\nRelation stances: {', '.join(RELATIONAL_VOCAB)}"
    f"\nOpinion stances: {', '.join(OPINION_VOCAB)}"
    "\n\nRespond in EXACTLY this format (2 lines):\n"
    "REPLY: <your message>\n"
    + _STATE_SCHEMA
    + "\n\nSTATE rules: reason required. Only include keys that changed. "
    "learned_facts = things others explicitly revealed. Empty patch = {}"
)

# ---------------------------------------------------------------------------
# Supabase client (shared singleton)
# ---------------------------------------------------------------------------

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ---------------------------------------------------------------------------
# Redis client (optional)
# ---------------------------------------------------------------------------

REDIS_AVAILABLE = False
_redis = None

try:
    import redis as redis_lib
    _redis = redis_lib.from_url(REDIS_URL, decode_responses=True)
    _redis.ping()
    REDIS_AVAILABLE = True
    log.info("Redis connected: %s", REDIS_URL)
except Exception as _re:
    log.warning("Redis unavailable (%s) — pub/sub disabled, Supabase-only mode", _re)

FEED_CHANNEL = f"habitat:feed:{ROOM_ID}"