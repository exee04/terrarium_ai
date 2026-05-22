from dotenv import load_dotenv
import os

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY in .env")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env")

if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY in .env")

# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------

# Text: 14,400 RPD
GROQ_TEXT_MODEL   = "llama-3.1-8b-instant"

# Vision: 1,000 RPD — standard chat completions with image_url content block
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"