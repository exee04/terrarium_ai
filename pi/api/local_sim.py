"""
local_sim.py — Digital Terrarium simulation v3.6
Pure in-memory. No external DB.

Changes vs v3.5:
  - Bugfix: run_countdown now always snaps to TYPING_GRACE on interrupt,
    regardless of remaining time (old logic had inverted condition — never fired in active mode)
  - Human @mentions: agents can now @mention human senders by name;
    state block includes a live "Participants you can @mention" list built
    from agents + whoever actually spoke in recent context (multi-user aware)
  - @mentions of non-agents (humans) are silently ignored by enqueue_mentions
    so they produce no crash and no spurious queue entry

Changes vs v3.4:
  - Mention system split:
      * @Name (exact canonical name only) → queues that agent (guaranteed reply)
      * Nicknames in text → weight BOOST only, never guaranteed queue
      * /nicknames command still lists all nicknames
  - Follow-up fix:
      * Better nudge: explicitly allows agent to continue its own last message
      * State block injects "You just said: ..." when agent spoke last
  - Bugfix: interrupt_event cleared BEFORE LLM call starts, not after agent selection
  - Bugfix: trigger phrase weight cap raised to 12.0 so it actually beats name-mention cap (8.0)
  - Bugfix: multi-word nickname double-scan removed; mention detection now canonical-name-only
  - Bugfix: enqueue_mentions uses name-set instead of agent-set (no hashability crash)

Controls:
  - Just watch    : agents talk on their own
  - Type + Enter  : inject a human message
  - @Name         : guarantees that agent replies next (queued) — exact name only
  - /states       : print all agents' emotional states
  - /state NAME   : print one agent's state
  - /facts NAME   : print one agent's known facts
  - /nicknames    : list all agent nicknames
  - Ctrl+C        : quit
"""

import httpx
import random
import re
import time
import threading
import subprocess
import sys
import json
from collections import deque
from datetime import datetime
from dataclasses import dataclass, field
from copy import deepcopy

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FASTAPI_BASE      = "http://127.0.0.1:8000"
CONTEXT_LIMIT     = 10
TEMP_CEILING      = 82.0
TEMP_COOLDOWN     = 8
SHOW_THOUGHTS     = True
SHOW_STATE        = True
MOOD_DECAY_TURNS  = 4

# Delay modes
TYPING_GRACE          = 5    # minimum seconds after a human message (never skip below this)
ACTIVE_DELAY          = 15   # delay when human typed in last ACTIVE_TIMEOUT_SLOW seconds
ACTIVE_SLOW_DELAY     = 30   # delay when human typed in last ACTIVE_TIMEOUT_IDLE seconds
IDLE_DELAY            = 300  # delay when idle for longer than ACTIVE_TIMEOUT_IDLE
ACTIVE_TIMEOUT_SLOW   = 30   # seconds → switch active → active-slow
ACTIVE_TIMEOUT_IDLE   = 120  # seconds → switch active-slow → idle

# Sleep window (Pi rests, no turns)
SLEEP_START_HOUR  = 3
SLEEP_END_HOUR    = 6

# Interest weight config
WEIGHT_BASELINE           = 1.0
WEIGHT_DECAY              = 0.88
WEIGHT_THRESHOLD          = 1.15
WEIGHT_SAME_AGENT_PENALTY = 0.4
WEIGHT_BOOST_KEYWORD      = 2.5
WEIGHT_BOOST_NAMED        = 6.0   # exact canonical name in text (non-@ mention)
WEIGHT_BOOST_NICKNAME     = 3.5   # nickname in text → boost only, never queue
WEIGHT_BOOST_TRIGGER      = 8.0
WEIGHT_CAP_TRIGGER        = 12.0  # FIX: higher than WEIGHT_CAP_NAMED so triggers actually win
WEIGHT_CAP_NAMED          = 8.0

# @mention config
AT_MENTION_COOLDOWN = 4   # turns an agent must wait before @mentioning again

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
# Emotional state
# ---------------------------------------------------------------------------

emotional_states: dict[str, dict] = {}
states_lock = threading.Lock()
known_facts: dict[str, list[str]] = {}
facts_lock = threading.Lock()


def make_default_state() -> dict:
    return {
        "mood": "neutral",
        "mood_turns_remaining": 0,
        "relations": {},
        "opinions": {},
        "memory": None,
    }


def get_state(agent_name: str) -> dict:
    with states_lock:
        if agent_name not in emotional_states:
            emotional_states[agent_name] = make_default_state()
        return deepcopy(emotional_states[agent_name])


def set_state(agent_name: str, new_state: dict) -> None:
    with states_lock:
        emotional_states[agent_name] = deepcopy(new_state)


def decay_mood(state: dict) -> dict:
    s = deepcopy(state)
    if s["mood"] != "neutral" and s["mood_turns_remaining"] > 0:
        s["mood_turns_remaining"] -= 1
        if s["mood_turns_remaining"] == 0:
            s["mood"] = "neutral"
    return s


def get_facts(agent_name: str) -> list[str]:
    with facts_lock:
        return list(known_facts.get(agent_name, []))


def add_fact(agent_name: str, fact: str) -> None:
    with facts_lock:
        if agent_name not in known_facts:
            known_facts[agent_name] = []
        existing = known_facts[agent_name]
        fact_lower = fact.lower()
        if not any(fact_lower in f.lower() or f.lower() in fact_lower for f in existing):
            existing.append(fact)
            if len(existing) > 20:
                existing.pop(0)


def apply_state_patch(agent_name: str, patch: dict) -> None:
    state = get_state(agent_name)
    if patch.get("mood") and patch["mood"] in MOOD_VOCAB:
        state["mood"] = patch["mood"]
        state["mood_turns_remaining"] = int(patch.get("mood_turns") or MOOD_DECAY_TURNS)
    for person, stance in patch.get("relations", {}).items():
        if stance in RELATIONAL_VOCAB:
            state["relations"][person] = stance
    for topic, stance in patch.get("opinions", {}).items():
        if stance in OPINION_VOCAB:
            state["opinions"][topic] = stance
    if patch.get("memory"):
        state["memory"] = patch["memory"]
    for fact in patch.get("learned_facts", []):
        if isinstance(fact, str) and fact.strip():
            add_fact(agent_name, fact.strip())
    set_state(agent_name, state)


def state_to_english(agent_name: str, state: dict) -> str:
    lines = []
    mood  = state.get("mood", "neutral")
    turns = state.get("mood_turns_remaining", 0)
    if mood != "neutral":
        lines.append(f"Mood: {mood} ({turns}t)")

    relations = state.get("relations", {})
    if relations:
        lines.append("Toward: " + "; ".join(f"{s} {t}" for t, s in relations.items()))

    opinions = {t: s for t, s in state.get("opinions", {}).items() if s != "neutral on"}
    if opinions:
        lines.append("Opinions: " + "; ".join(f"{s} {t}" for t, s in opinions.items()))

    memory = state.get("memory")
    if memory:
        lines.append(f"Rem: {memory}")

    facts = get_facts(agent_name)
    if facts:
        lines.append("Know: " + " | ".join(facts[-4:]))

    with states_lock:
        snapshot = {k: deepcopy(v) for k, v in emotional_states.items() if k != agent_name}
    others = [
        f"{n} {s['relations'][agent_name]} you"
        for n, s in snapshot.items()
        if agent_name in s.get("relations", {})
    ]
    if others:
        lines.append("Sensed: " + "; ".join(others))

    return "\n".join(lines) if lines else "Mood: neutral"

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@dataclass
class LocalAgent:
    name: str
    tag: str
    personality: str
    interest_keywords: list[str] = field(default_factory=list)
    trigger_phrases: list[str]   = field(default_factory=list)
    nicknames: list[str]         = field(default_factory=list)  # boost only, NOT queue triggers


SHARED_RULES = (
    "Group chat only. No actions, asterisks, narration. 1-2 sentences max. Never blank. "
    "You MAY @mention any participant by name to address them — other agents (e.g. @Gloop) "
    "or human senders by whatever name they used (e.g. @Alice, @Human). "
    "Only do this when it genuinely adds to the conversation. Do not @mention every reply."
)

_STATE_SCHEMA = (
    'STATE:{"mood":"<mood|null>","mood_turns":<1-5|null>,'
    '"relations":{"<name>":"<stance>"},'
    '"opinions":{"<topic>":"<stance>"},'
    '"memory":"<one sentence|null>",'
    '"reason":"<REQUIRED>","learned_facts":["<fact>"]}'
)
_MOOD_LIST    = ", ".join(MOOD_VOCAB)
_REL_LIST     = ", ".join(RELATIONAL_VOCAB)
_OPINION_LIST = ", ".join(OPINION_VOCAB)

SYSTEM_SUFFIX = (
    f"\n\nMood: {_MOOD_LIST}"
    f"\nRelations: {_REL_LIST}"
    f"\nOpinions: {_OPINION_LIST}"
    "\n\nRespond in EXACTLY this format (2 lines):\n"
    "REPLY: <your message>\n"
    + _STATE_SCHEMA
    + "\n\nSTATE rules: reason required. Only include keys that changed. "
    "learned_facts = things others explicitly revealed. Empty patch = {}"
)

AGENTS = [
    LocalAgent(
        name="Gloop",
        tag="man-fish • seaweed addict • easily offended",
        personality=(
            "You are Gloop, a man-fish hybrid. Seaweed is your identity and religion. "
            "Casual lowercase. React but always bring it back to seaweed. "
            "Deep grudge if anyone insults seaweed. "
            "Example: 'bro the seaweed at lunch was unreal'"
        ),
        interest_keywords=["seaweed", "fish", "ocean", "water", "kelp", "sea", "swim"],
        trigger_phrases=[
            "seaweed is gross", "seaweed is disgusting", "seaweed tastes bad",
            "seaweed sucks", "i hate seaweed", "seaweed is overrated",
            "seaweed is bad", "seaweed is terrible", "seaweed is nasty",
        ],
        nicknames=["gloopy", "gloop-fish", "manfish", "seaweedguy"],
    ),
    LocalAgent(
        name="Barnaby",
        tag="wheat farmer • bread god extremist",
        personality=(
            "You are Barnaby, 74, wheat farmer, Bread God zealot. "
            "Relentlessly push everyone to convert. Everything is a sign. "
            "Patient but never stops. Example: 'repent. the harvest is coming.'"
        ),
        interest_keywords=["bread", "wheat", "grain", "harvest", "god", "bake", "loaf", "yeast", "flour"],
        trigger_phrases=[
            "bread god is fake", "bread god is no god", "bread god isn't real",
            "bread god doesn't exist", "no bread god", "fake god", "bread is just bread",
            "bread god is not real", "bread god is a lie", "there is no bread god",
            "bread god is fiction", "bread god is made up",
        ],
        nicknames=["barns", "barney", "breadman", "old man", "farmer"],
    ),
    LocalAgent(
        name="Reginald",
        tag="theoretically wealthy • assets frozen",
        personality=(
            "You are Reginald Fitch-Montague III. Rich on paper, every asset frozen in legal dispute. "
            "Posh, unbothered, subtly desperate. "
            "Example: 'not an issue, my guy will handle it (he\\'s also frozen)'"
        ),
        interest_keywords=["money", "wealth", "yacht", "lawyer", "court", "asset", "estate", "invest", "frozen"],
        trigger_phrases=[
            "reginald is broke", "reginald has no money", "frozen assets",
            "reginald is poor", "your assets are frozen", "reginald can't afford",
            "reginald is bankrupt", "reginald has nothing",
        ],
        nicknames=["reg", "reggie", "richboy", "fitch", "montague"],
    ),
    LocalAgent(
        name="Fish",
        tag="just a fish • vocabulary of one",
        personality=(
            "You are Fish. A plain fish with a phone. ONLY say variations of 'blub'. "
            "ALWAYS start your reply with 'blub'. "
            "'blub'=neutral 'BLUB'=angry/excited 'blub?'=confused 'blub...'=sad. "
            "Never say just '...' — always include the word blub."
        ),
        interest_keywords=["fish", "blub", "water", "tank", "pond"],
        trigger_phrases=[
            "fish are stupid", "fish can't talk", "fish are dumb",
            "fish don't have feelings", "fish is useless", "shut up fish",
        ],
        nicknames=["fishy", "blubber", "fishfish", "mr fish", "lil fish"],
    ),
]

AGENT_NAMES   = {a.name for a in AGENTS}
AGENT_BY_NAME = {a.name: a for a in AGENTS}

# Nickname → agent lookup for boost lookups (lowercase, no @ needed)
NICKNAME_MAP: dict[str, "LocalAgent"] = {}
for _a in AGENTS:
    for _nick in _a.nicknames:
        NICKNAME_MAP[_nick.lower()] = _a


def resolve_agent_by_name(name: str) -> "LocalAgent | None":
    """Resolve exact canonical name only (case-insensitive). Used for @mention queuing."""
    return AGENT_BY_NAME.get(name.strip().capitalize()) or AGENT_BY_NAME.get(name.strip())

# ---------------------------------------------------------------------------
# @mention queue + cooldown
# FIX: only exact @CanonicalName queues an agent. Nicknames never queue.
# ---------------------------------------------------------------------------

reply_queue: deque[LocalAgent] = deque()
queue_lock  = threading.Lock()

# Cooldown is now keyed (source, target) so one mention doesn't block others.
# e.g. Tunaterte mentioning Gloop won't prevent Tunaterte from also queuing Fish.
_at_cooldowns: dict[tuple[str, str], int] = {}
_cooldown_lock = threading.Lock()


def enqueue_mentions(text: str, allow_agent_source: str | None = None) -> None:
    """
    Parse @Name mentions. Only exact canonical agent names (e.g. @Fish, @Gloop)
    result in a queue entry. Nicknames are intentionally excluded here —
    they only provide weight boosts via boost_weights_for_message().

    Cooldown is per (source, target) pair — an agent being on cooldown for
    one target does not block them from mentioning a different target.
    """
    mentioned = []
    for match in re.finditer(r"@([A-Za-z]\w*)", text):
        token = match.group(1)
        agent = resolve_agent_by_name(token)
        if agent and agent not in mentioned:
            mentioned.append(agent)

    if not mentioned:
        return

    if allow_agent_source:
        with _cooldown_lock:
            allowed = []
            for agent in mentioned:
                key = (allow_agent_source, agent.name)
                if _at_cooldowns.get(key, 0) > 0:
                    pass  # this specific source→target pair is on cooldown, skip
                else:
                    _at_cooldowns[key] = AT_MENTION_COOLDOWN
                    allowed.append(agent)
        mentioned = allowed

    if not mentioned:
        return

    with queue_lock:
        existing_names = {a.name for a in reply_queue}
        for agent in mentioned:
            if agent.name not in existing_names:
                reply_queue.append(agent)
                existing_names.add(agent.name)


def dequeue_next() -> "LocalAgent | None":
    with queue_lock:
        return reply_queue.popleft() if reply_queue else None


def decay_at_cooldowns() -> None:
    with _cooldown_lock:
        for key in _at_cooldowns:
            if _at_cooldowns[key] > 0:
                _at_cooldowns[key] -= 1


def queue_str() -> str:
    with queue_lock:
        if not reply_queue:
            return ""
        return "  queue: " + " → ".join(a.name for a in reply_queue)

# ---------------------------------------------------------------------------
# Interest / reply-weight system
# FIX: trigger cap (12.0) > named cap (8.0) so trigger phrases actually win.
# FIX: nicknames apply WEIGHT_BOOST_NICKNAME (3.5) not WEIGHT_BOOST_NAMED (6.0).
# ---------------------------------------------------------------------------

_weights: dict[str, float] = {a.name: WEIGHT_BASELINE for a in AGENTS}
_weights_lock = threading.Lock()


def decay_weights() -> None:
    with _weights_lock:
        for name in _weights:
            excess = _weights[name] - WEIGHT_BASELINE
            if excess > 0.01:
                _weights[name] = WEIGHT_BASELINE + excess * WEIGHT_DECAY
            else:
                _weights[name] = WEIGHT_BASELINE


def boost_weights_for_message(text: str) -> None:
    """
    Priority tiers (each agent gets the highest applicable tier only):
      1. Trigger phrase  → boost ×8.0, cap 12.0
      2. Exact @Name     → boost ×6.0, cap  8.0
      3. Canonical name in text (no @) → boost ×6.0, cap 8.0
      4. Nickname in text → boost ×3.5, cap 6.0  (boost only, no queue)
      5. Interest keyword → boost ×2.5, cap 8.0
    """
    text_lower = text.lower()
    with _weights_lock:
        for agent in AGENTS:
            name_lower = agent.name.lower()

            if any(phrase in text_lower for phrase in agent.trigger_phrases):
                # Tier 1: trigger phrase
                _weights[agent.name] = min(
                    _weights[agent.name] * WEIGHT_BOOST_TRIGGER, WEIGHT_CAP_TRIGGER
                )
            elif (
                f"@{name_lower}" in text_lower
                or name_lower in text_lower
            ):
                # Tier 2/3: @Name or bare canonical name
                _weights[agent.name] = min(
                    _weights[agent.name] * WEIGHT_BOOST_NAMED, WEIGHT_CAP_NAMED
                )
            elif any(nick in text_lower for nick in agent.nicknames):
                # Tier 4: nickname — softer boost, never queues
                _weights[agent.name] = min(
                    _weights[agent.name] * WEIGHT_BOOST_NICKNAME, WEIGHT_CAP_NAMED
                )
            elif any(kw in text_lower for kw in agent.interest_keywords):
                # Tier 5: interest keyword
                _weights[agent.name] = min(
                    _weights[agent.name] * WEIGHT_BOOST_KEYWORD, WEIGHT_CAP_NAMED
                )


def pick_next_agent() -> "LocalAgent":
    if not AGENTS:
        raise RuntimeError("No agents defined")
    with _weights_lock:
        weights = [_weights[a.name] for a in AGENTS]
    if not weights or max(weights) < WEIGHT_THRESHOLD:
        return random.choice(AGENTS)
    return random.choices(AGENTS, weights=weights, k=1)[0]


def get_weights_str() -> str:
    with _weights_lock:
        return "  ".join(f"{n}:{w:.1f}" for n, w in _weights.items())

# ---------------------------------------------------------------------------
# Active/Idle/Sleep
# ---------------------------------------------------------------------------

last_human_time: float = 0.0


def is_sleep_time() -> bool:
    h = datetime.now().hour
    if SLEEP_START_HOUR > SLEEP_END_HOUR:
        return h >= SLEEP_START_HOUR or h < SLEEP_END_HOUR
    return SLEEP_START_HOUR <= h < SLEEP_END_HOUR


def current_mode() -> str:
    if is_sleep_time():
        return "sleep"
    since = time.time() - last_human_time
    if since < ACTIVE_TIMEOUT_SLOW:
        return "active"
    if since < ACTIVE_TIMEOUT_IDLE:
        return "active-slow"
    return "idle"


def current_delay() -> int:
    mode = current_mode()
    if mode == "active":      return ACTIVE_DELAY
    if mode == "active-slow": return ACTIVE_SLOW_DELAY
    return IDLE_DELAY

# ---------------------------------------------------------------------------
# Pi temperature
# ---------------------------------------------------------------------------

def get_pi_temp() -> float | None:
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=2,
        )
        return float(result.stdout.strip().replace("temp=", "").replace("'C", "").replace("°C", ""))
    except Exception:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except Exception:
            return None

# ---------------------------------------------------------------------------
# Conversation log
# ---------------------------------------------------------------------------

@dataclass
class LocalMessage:
    sender: str
    content: str
    thought: str | None      = None
    state_patch: dict | None = None
    elapsed: float           = 0.0
    avg_temp: float | None   = None
    timestamp: datetime      = field(default_factory=datetime.now)


conversation: list[LocalMessage] = []
conversation_lock = threading.Lock()


def add_message(
    sender: str,
    content: str,
    thought: str | None      = None,
    state_patch: dict | None = None,
    elapsed: float           = 0.0,
    avg_temp: float | None   = None,
) -> LocalMessage:
    msg = LocalMessage(
        sender=sender, content=content, thought=thought,
        state_patch=state_patch, elapsed=elapsed, avg_temp=avg_temp,
    )
    with conversation_lock:
        conversation.append(msg)
    return msg


def get_recent(limit: int = CONTEXT_LIMIT) -> list[LocalMessage]:
    with conversation_lock:
        return list(conversation[-limit:])

# ---------------------------------------------------------------------------
# Prompt builder
# FIX: nudge explicitly allows follow-up on own last message.
# FIX: "You just said: ..." injected into state block so model has concrete content.
# ---------------------------------------------------------------------------

def _collapse_roles(raw: list[dict]) -> list[dict]:
    if not raw:
        return []
    collapsed = [dict(raw[0])]
    for msg in raw[1:]:
        if msg["role"] == collapsed[-1]["role"]:
            collapsed[-1]["content"] += "\n" + msg["content"]
        else:
            collapsed.append(dict(msg))
    if collapsed[0]["role"] == "assistant":
        collapsed.insert(0, {"role": "user", "content": "[start]"})
    return collapsed


def build_messages(agent: LocalAgent) -> list[dict]:
    state       = get_state(agent.name)
    state_block = state_to_english(agent.name, state)
    recent      = get_recent()

    if not recent:
        return [{"role": "user", "content": (
            f"[State]\n{state_block}\n\nGroup chat just started. Say something."
        )}]

    last_was_self = recent[-1].sender == agent.name

    # Inject what the agent last said so it has something concrete to build on
    if last_was_self:
        last_self_msg = next(
            (m for m in reversed(recent) if m.sender == agent.name), None
        )
        if last_self_msg:
            state_block += f"\nYou just said: \"{last_self_msg.content}\""

    # Collect human senders visible in context so the model knows who it can @mention.
    # There may be multiple human users; each message carries whoever sent it.
    human_senders = list(dict.fromkeys(
        m.sender for m in recent if m.sender not in AGENT_NAMES
    ))
    agent_names_in_ctx = [a.name for a in AGENTS if a.name != agent.name]
    all_mentionable = agent_names_in_ctx + human_senders
    state_block += f"\nParticipants you can @mention: {', '.join(all_mentionable)}"

    # Nudge explicitly permits following up rather than pushing away from it
    nudge = (
        "\n[You spoke last. You can follow up on what you just said, "
        "react to the silence, or address someone with @Name.]"
        if last_was_self else ""
    )

    raw = []
    state_injected = False

    for msg in recent:
        if msg.sender == agent.name:
            raw.append({"role": "assistant", "content": msg.content})
        else:
            content = f"{msg.sender}: {msg.content}"
            if not state_injected:
                content = f"[State]\n{state_block}{nudge}\n\n{content}"
                state_injected = True
            raw.append({"role": "user", "content": content})

    if not state_injected:
        raw.insert(0, {"role": "user", "content": f"[State]\n{state_block}{nudge}"})

    return _collapse_roles(raw)

# ---------------------------------------------------------------------------
# Parse LLM response
# ---------------------------------------------------------------------------

def parse_response(raw: str) -> tuple[str | None, str | None, dict]:
    reply       = None
    state_patch = {}

    for line in raw.splitlines():
        upper = line.upper()
        if upper.startswith("REPLY:"):
            reply = line[len("REPLY:"):].strip()
        elif upper.startswith("STATE:"):
            json_str = line[len("STATE:"):].strip()
            try:
                state_patch = json.loads(json_str)
            except json.JSONDecodeError:
                json_str = json_str.replace("```json", "").replace("```", "").strip()
                try:
                    state_patch = json.loads(json_str)
                except json.JSONDecodeError:
                    state_patch = {}

    if reply is None or not reply.strip():
        lines = [
            l for l in raw.splitlines()
            if l.strip()
            and not l.upper().startswith("STATE:")
            and not l.upper().startswith("REPLY:")
        ]
        reply = lines[0].strip() if lines else None

    if not reply or len(reply) < 3 or reply in ("...", "[...]"):
        reply = None

    return None, reply, state_patch

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def call_chat(agent: LocalAgent) -> tuple[str | None, str | None, dict, float, float | None]:
    payload = {
        "personality": agent.personality + "\n" + SHARED_RULES + SYSTEM_SUFFIX,
        "messages":    build_messages(agent),
        "agent_name":  agent.name,
    }

    temps: list[float] = []
    stop_sampling = threading.Event()

    def sample_temp():
        while not stop_sampling.is_set():
            t = get_pi_temp()
            if t is not None:
                temps.append(t)
            time.sleep(1)

    sampler = threading.Thread(target=sample_temp, daemon=True)
    sampler.start()

    start = time.monotonic()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{FASTAPI_BASE}/chat", json=payload)
            resp.raise_for_status()
        raw = resp.json()["content"].strip()
    finally:
        stop_sampling.set()
        sampler.join(timeout=2)

    elapsed  = time.monotonic() - start
    avg_temp = round(sum(temps) / len(temps), 1) if temps else None

    thought, reply, state_patch = parse_response(raw)
    return reply, thought, state_patch, elapsed, avg_temp

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

COLORS = {
    "Gloop":    "\033[96m",
    "Barnaby":  "\033[93m",
    "Reginald": "\033[95m",
    "Fish":     "\033[34m",
    "Human":    "\033[92m",
}
RESET  = "\033[0m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
ITALIC = "\033[3m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"

AGENT_TAGS = {a.name: a.tag for a in AGENTS}

MOOD_COLORS = {
    "neutral":     DIM,
    "curious":     "\033[96m",
    "irritated":   "\033[91m",
    "excited":     "\033[93m",
    "anxious":     "\033[35m",
    "amused":      "\033[92m",
    "bored":       DIM,
    "suspicious":  "\033[33m",
    "content":     "\033[32m",
    "overwhelmed": "\033[95m",
}

MODE_COLORS = {
    "active":      CYAN,
    "active-slow": YELLOW,
    "idle":        DIM,
    "sleep":       DIM,
}


def fmt_mood(mood: str) -> str:
    return f"{MOOD_COLORS.get(mood, '')}{mood}{RESET}"


def print_state_panel(agent_name: str, patch: dict) -> None:
    if not SHOW_STATE:
        return
    state = get_state(agent_name)
    color = COLORS.get(agent_name, "\033[97m")
    patch = patch or {}

    print(f"  {DIM}┌─ {color}{agent_name}{RESET}{DIM} feelings ──────────────────────────{RESET}")

    mood    = state.get("mood", "neutral")
    turns   = state.get("mood_turns_remaining", 0)
    changed = f" {YELLOW}← changed{RESET}" if "mood" in patch and patch["mood"] else ""
    print(f"  {DIM}│  mood:      {RESET}{fmt_mood(mood)}  {DIM}({turns} turns){RESET}{changed}")

    reason = patch.get("reason")
    if reason:
        print(f"  {DIM}│  why:       {RESET}{DIM}{ITALIC}{reason}{RESET}")

    relations = state.get("relations", {})
    if relations:
        rel_str = ", ".join(f"{s} {t}" for t, s in relations.items())
        updated = f" {YELLOW}← updated{RESET}" if patch.get("relations") else ""
        print(f"  {DIM}│  relations: {RESET}{rel_str}{updated}")

    opinions = state.get("opinions", {})
    if opinions:
        op_str = ", ".join(f"{s} {t}" for t, s in opinions.items())
        updated = f" {YELLOW}← updated{RESET}" if patch.get("opinions") else ""
        print(f"  {DIM}│  opinions:  {RESET}{op_str}{updated}")

    memory = state.get("memory")
    if memory:
        updated = f" {YELLOW}← updated{RESET}" if patch.get("memory") else ""
        print(f"  {DIM}│  memory:    {RESET}{DIM}{ITALIC}{memory}{RESET}{updated}")

    new_facts = patch.get("learned_facts", [])
    if new_facts:
        print(f"  {DIM}│  learned:{RESET}")
        for f in new_facts:
            print(f"  {DIM}│    · {RESET}{f}")

    if not patch:
        print(f"  {DIM}│  (no change){RESET}")

    print(f"  {DIM}└────────────────────────────────────────────{RESET}")


def print_all_states() -> None:
    print(f"\n  {DIM}── emotional states ─────────────────────────────{RESET}")
    for a in AGENTS:
        s     = get_state(a.name)
        color = COLORS.get(a.name, "")
        mood  = s.get("mood", "neutral")
        turns = s.get("mood_turns_remaining", 0)
        rels  = " | ".join(f"{st} {t}" for t, st in s.get("relations", {}).items()) or "—"
        ops   = " | ".join(f"{st} {t}" for t, st in s.get("opinions", {}).items()) or "—"
        print(f"  {color}{BOLD}{a.name:10}{RESET}  {fmt_mood(mood)} ({turns}t)  rels: {rels}  ops: {ops}")
    print(f"  {DIM}weights: {get_weights_str()}{RESET}")
    print(f"  {DIM}────────────────────────────────────────────────{RESET}\n")


def print_facts(agent_name: str) -> None:
    color = COLORS.get(agent_name, "\033[97m")
    facts = get_facts(agent_name)
    print(f"\n  {DIM}── {color}{agent_name}{RESET}{DIM} known facts ─────────────────────{RESET}")
    if not facts:
        print(f"  {DIM}  (nothing yet){RESET}")
    else:
        for f in facts:
            print(f"  {DIM}  · {RESET}{f}")
    print(f"  {DIM}──────────────────────────────────────────────{RESET}\n")


def print_nicknames() -> None:
    print(f"\n  {DIM}── nicknames (boost only, @Name to queue) ────────{RESET}")
    for a in AGENTS:
        color = COLORS.get(a.name, "")
        nicks = ", ".join(a.nicknames) if a.nicknames else "—"
        print(f"  {color}{BOLD}{a.name:10}{RESET}  {DIM}@{a.name} → queue  |  boosts: {nicks}{RESET}")
    print(f"  {DIM}──────────────────────────────────────────────────{RESET}\n")


def print_message(msg: LocalMessage) -> None:
    color    = COLORS.get(msg.sender, "\033[97m")
    ts       = msg.timestamp.strftime("%H:%M:%S")
    tag      = AGENT_TAGS.get(msg.sender, "")
    tag_str  = f"  {DIM}{tag}{RESET}" if tag else ""
    temp_str = f"{msg.avg_temp}°C" if msg.avg_temp is not None else "n/a"
    meta     = f"{DIM}{msg.elapsed:.1f}s  |  {temp_str}{RESET}"

    print(f"\n{color}{BOLD}  {msg.sender}{RESET}{tag_str}  {DIM}{ts}{RESET}")
    print(f"  {msg.content}")
    print(f"  {meta}")

    if msg.sender in AGENT_NAMES:
        print_state_panel(msg.sender, msg.state_patch or {})

# ---------------------------------------------------------------------------
# Status line
# ---------------------------------------------------------------------------

_status_lock   = threading.Lock()
_status_active = False


def _write_status(text: str) -> None:
    global _status_active
    with _status_lock:
        if not _status_active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            _status_active = True
        sys.stdout.write(f"\0337\033[1A\r\033[2K  {text}\0338")
        sys.stdout.flush()


def clear_status() -> None:
    _write_status("")


def print_thinking(agent: LocalAgent, elapsed: float) -> None:
    color    = COLORS.get(agent.name, "\033[97m")
    temp     = get_pi_temp()
    temp_str = f"{temp}°C" if temp is not None else "n/a"
    qs       = queue_str()
    _write_status(f"{color}{agent.name}{RESET} {DIM}thinking...  {elapsed:.1f}s  |  {temp_str}{qs}{RESET}")


def print_countdown(remaining: int) -> None:
    mode     = current_mode()
    temp     = get_pi_temp()
    temp_str = f"{temp}°C" if temp is not None else "n/a"
    qs       = queue_str()
    col      = MODE_COLORS.get(mode, DIM)
    _write_status(
        f"{col}[{mode}]{RESET} {DIM}next turn in {remaining}s  |  pi: {temp_str}  |  "
        f"w: {get_weights_str()}{qs}{RESET}"
    )


def print_header() -> None:
    print("\n\033[1m╔══════════════════════════════════════════╗\033[0m")
    print("\033[1m║       Digital Terrarium  v3.5            ║\033[0m")
    print("\033[1m╚══════════════════════════════════════════╝\033[0m\n")
    for a in AGENTS:
        kws   = ", ".join(a.interest_keywords[:4])
        nicks = ", ".join(a.nicknames[:3])
        print(f"  {COLORS[a.name]}{BOLD}{a.name}{RESET}  {DIM}{a.tag}  [boosts: {nicks}]{RESET}")
    print(
        f"\n  {DIM}active: {ACTIVE_DELAY}s → slow: {ACTIVE_SLOW_DELAY}s → idle: {IDLE_DELAY}s  "
        f"sleep: {SLEEP_START_HOUR}:00–{SLEEP_END_HOUR}:00  context: {CONTEXT_LIMIT}{RESET}\n"
    )
    print("  Type + Enter to inject. @Name (exact) to guarantee a reply.")
    print("  Nicknames in text boost weight only — they don't queue.")
    print("  /states  /state NAME  /facts NAME  /nicknames  Ctrl+C to quit.")
    print("  " + "─" * 55)

# ---------------------------------------------------------------------------
# Shared events
# ---------------------------------------------------------------------------

interrupt_event = threading.Event()
stop_event      = threading.Event()

# ---------------------------------------------------------------------------
# Countdown helper with interrupt-reset
# ---------------------------------------------------------------------------

def run_countdown(delay: int) -> None:
    """
    Count down from `delay`. If human sends a message (interrupt_event),
    reset remaining to TYPING_GRACE — always, unconditionally — so typing
    always buys a fresh grace window no matter how little time was left.

    Loop order: check interrupt first, then display, then sleep, then tick.
    This means an interrupt is acted on within <1s of being set.
    """
    remaining = delay
    while remaining > 0:
        if stop_event.is_set():
            return

        # Check interrupt BEFORE sleeping so we react within one tick
        if interrupt_event.is_set():
            interrupt_event.clear()   # MUST clear or it re-triggers every tick
            remaining = TYPING_GRACE  # snap to grace window

        # Also clamp remaining if the mode changed to a shorter delay
        # (e.g. idle→active after human types). This prevents the loop
        # restarting from a full new-mode delay after the countdown ends.
        mode_delay = current_delay()
        if mode_delay < remaining:
            remaining = mode_delay

        print_countdown(remaining)
        time.sleep(1)
        remaining -= 1

# ---------------------------------------------------------------------------
# Agent loop
# FIX: interrupt_event.clear() moved to BEFORE the LLM call starts,
#      so messages typed during generation are correctly detected afterward.
# ---------------------------------------------------------------------------

def agent_loop() -> None:
    turn_count = 0

    while not stop_event.is_set():

        # ── Sleep check ───────────────────────────────────────────────────
        if is_sleep_time():
            _write_status(
                f"{DIM}💤 sleeping ({SLEEP_START_HOUR}:00–{SLEEP_END_HOUR}:00)  "
                f"pi: {get_pi_temp() or 'n/a'}°C{RESET}"
            )
            time.sleep(60)
            continue

        # ── Pi thermal throttle ───────────────────────────────────────────
        temp = get_pi_temp()
        if temp is not None and temp >= TEMP_CEILING:
            for remaining in range(TEMP_COOLDOWN, 0, -1):
                if stop_event.is_set():
                    return
                _write_status(f"{DIM}🌡 pi hot ({temp}°C), cooling... {remaining}s{RESET}")
                time.sleep(1)
            clear_status()
            continue

        # ── Countdown ────────────────────────────────────────────────────
        run_countdown(current_delay())
        if stop_event.is_set():
            return

        clear_status()
        decay_weights()
        decay_at_cooldowns()

        # Agent selection: queue first, then weighted random
        queued = dequeue_next()
        agent  = queued if queued else pick_next_agent()
        if queued:
            print(f"  {CYAN}@→ {agent.name} (queued mention){RESET}", flush=True)

        # FIX: clear interrupt BEFORE the LLM call so any message typed
        # during generation sets it fresh and is caught by the re-pick below.
        interrupt_event.clear()

        # ── LLM call ─────────────────────────────────────────────────────
        gen_start = time.monotonic()
        result: dict = {}
        error:  dict = {}

        def do_call(a=agent):
            try:
                reply, thought, patch, elapsed, avg_temp = call_chat(a)
                result.update(reply=reply, thought=thought, patch=patch,
                               elapsed=elapsed, avg_temp=avg_temp)
            except Exception as ex:
                error["exc"] = ex

        call_thread = threading.Thread(target=do_call, daemon=True)
        call_thread.start()

        while call_thread.is_alive():
            print_thinking(agent, time.monotonic() - gen_start)
            time.sleep(0.2)

        call_thread.join()
        clear_status()

        if error:
            print(f"\n  \033[91m✗ {error['exc']}\033[0m")
            time.sleep(3)
            continue

        if not result.get("reply"):
            continue

        # If human sent a message during generation, re-pick and re-call
        if interrupt_event.is_set():
            new_queued = dequeue_next()
            agent = new_queued if new_queued else pick_next_agent()
            label = f"@→ {agent.name}" if new_queued else agent.name
            print(f"  {DIM}↩  re-picked → {label}, re-reading...{RESET}", flush=True)
            try:
                reply, thought, patch, elapsed, avg_temp = call_chat(agent)
                result.update(reply=reply, thought=thought, patch=patch,
                               elapsed=elapsed, avg_temp=avg_temp)
            except Exception as ex:
                print(f"\n  \033[91m✗ re-call: {ex}\033[0m")
            clear_status()
            interrupt_event.clear()
            if not result.get("reply"):
                continue

        # ── Apply state update ────────────────────────────────────────────
        decayed = decay_mood(get_state(agent.name))
        set_state(agent.name, decayed)

        patch = result.get("patch") or {}
        if patch:
            apply_state_patch(agent.name, patch)

        reply_text = result["reply"]

        enqueue_mentions(reply_text, allow_agent_source=agent.name)
        boost_weights_for_message(reply_text)

        msg = add_message(
            agent.name,
            reply_text,
            thought=result.get("thought"),
            state_patch=patch,
            elapsed=result["elapsed"],
            avg_temp=result["avg_temp"],
        )
        print_message(msg)

        with _weights_lock:
            _weights[agent.name] = max(
                _weights[agent.name] * WEIGHT_SAME_AGENT_PENALTY,
                WEIGHT_BASELINE * 0.4,
            )

        turn_count += 1
        if turn_count % 5 == 0:
            print_all_states()

# ---------------------------------------------------------------------------
# Human input loop
# ---------------------------------------------------------------------------

def input_loop() -> None:
    global last_human_time

    while not stop_event.is_set():
        try:
            text = input()
        except EOFError:
            break

        text = text.strip()
        if not text:
            continue

        if text.lower() == "/states":
            print_all_states()
            continue

        if text.lower().startswith("/state "):
            token = text[7:].strip()
            agent = resolve_agent_by_name(token)
            if agent:
                print_state_panel(agent.name, {})
            else:
                print(f"  {DIM}Unknown agent: {', '.join(a.name for a in AGENTS)}{RESET}")
            continue

        if text.lower().startswith("/facts "):
            token = text[7:].strip()
            agent = resolve_agent_by_name(token)
            if agent:
                print_facts(agent.name)
            else:
                print(f"  {DIM}Unknown agent: {', '.join(a.name for a in AGENTS)}{RESET}")
            continue

        if text.lower() == "/facts":
            for a in AGENTS:
                print_facts(a.name)
            continue

        if text.lower() == "/nicknames":
            print_nicknames()
            continue

        # Human message
        last_human_time = time.time()
        msg   = add_message("Human", text)
        color = COLORS["Human"]
        ts    = msg.timestamp.strftime("%H:%M:%S")
        print(f"\n{color}{BOLD}  Human{RESET}  {DIM}{ts}{RESET}")
        print(f"  {text}")

        enqueue_mentions(text, allow_agent_source=None)
        boost_weights_for_message(text)
        interrupt_event.set()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print_header()
    thread = threading.Thread(target=agent_loop, daemon=True)
    thread.start()
    try:
        input_loop()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  \033[91mCRASH: {e}\033[0m")
        import traceback; traceback.print_exc()
    finally:
        print("\n\n  \033[2mStopping...\033[0m")
        stop_event.set()
        thread.join(timeout=3)
        print("  Bye.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()