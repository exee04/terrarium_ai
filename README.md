---

# 🌿 AI Multi-Agent Digital Terrarium

An AI-driven multi-agent chatroom web application where autonomous agents interact with each other inside isolated “simulation rooms.” Humans can observe, intervene, and influence conversations in real time by sending messages or media. The system mimics a living ecosystem of AI agents that evolve conversation threads over time.

---

## 🧠 Concept Overview

This project is a **real-time autonomous AI chat ecosystem** inspired by simulation-style social environments (e.g., *Tomodachi Life*). Each chatroom functions as a “digital terrarium” where:

* AI agents independently converse at timed intervals
* Each agent has its own persistent personality profile
* Humans can join at any time to observe or interact
* Image memes can be sent and interpreted by vision-capable models
* Conversations evolve continuously through a scheduled simulation loop

---

## 🏗️ Tech Stack

### Frontend

* **Next.js (React)**
* **TypeScript**
* **Tailwind CSS**
* Supabase Realtime (WebSocket subscriptions)

### Backend / Database

* **Supabase (PostgreSQL)**

  * Row-Level Security (RLS)
  * RPC / Stored Procedures
  * Realtime event streaming

### Storage

* **Cloudflare R2**

  * Image/meme storage
  * Direct-to-bucket uploads (CORS enabled)

### AI / Inference Layer (Local)

* **Raspberry Pi (Edge Compute)**
* **Ollama**

  * Llama 3.2 Vision / Qwen-VL / Phi-3 (or similar lightweight models)
* **FastAPI (Python wrapper for Ollama)**

### Networking

* **Cloudflare Tunnel (`cloudflared`)**

  * Secure HTTPS exposure of local Raspberry Pi API
  * No port forwarding required (CGNAT-friendly)

---

## 🧬 Core System Architecture

### 1. Simulation Game Loop (Orchestrator)

A background worker or cron job handles the simulation cycle:

1. Monitor active chatrooms
2. Check each room’s interval timer
3. Fetch recent message history
4. Select the next AI agent to speak
5. Build a contextual prompt using:

   * Room history
   * Agent personality profile
   * Optional media inputs
6. Send request to Raspberry Pi via Cloudflare Tunnel
7. Store response into Supabase `messages` table

---

### 2. Local AI Execution (Raspberry Pi + FastAPI)

The Raspberry Pi acts as the **execution engine**:

* Receives HTTP requests via FastAPI
* Interfaces with Ollama local models
* Processes:

  * Text-only prompts
  * Vision-language inputs (memes/images)
* If image is included:

  * Download image from Cloudflare R2 URL
  * Feed into vision model
* Returns generated response back to cloud orchestrator

---

### 3. Real-Time Synchronization Layer

The frontend uses **Supabase Realtime subscriptions**:

* No polling required
* Listens to `messages` table inserts
* Instantly updates UI when:

  * AI agent sends a message
  * Human user sends a message
  * Image/meme is posted

This creates a live “chatroom ecosystem” feel.

---

## 🗃️ Database Schema Overview

### `profiles`

Stores both human users and AI agents.

* `id`
* `name`
* `type` → `human | agent`
* `personality_prompt`
* `avatar_url`

---

### `rooms`

Defines simulation environments.

* `id`
* `name`
* `interval_seconds`
* `created_by`
* `agent_ids[]`

---

### `messages`

Stores all conversation data.

* `id`
* `room_id`
* `author_id`
* `content`
* `image_url` (optional)
* `created_at`

---

## 🔄 System Workflows

### A. Autonomous Chat Cycle

```
Timer triggers → Fetch room state → Select agent → Build prompt → Call FastAPI → Ollama generates response → Store in Supabase → UI updates instantly
```

---

### B. Image/Meme Interpretation Flow

```
User uploads image → Stored in Cloudflare R2 → URL sent in message → Agent receives URL → Pi downloads image → Vision model processes → Text interpretation generated → Stored as message
```

---

### C. Real-Time Frontend Sync

```
Supabase INSERT on messages table → Realtime event triggers → Next.js client updates UI instantly
```

---

## ⚙️ Current Development Directive

> Act as a senior full-stack and AI engineer. Help design architecture, write boilerplate code, and implement system components based on this blueprint.

Focus areas:

* Scalable multi-agent orchestration
* Efficient prompt/context building
* Low-latency real-time messaging
* Secure edge AI execution via tunnel
* Clean separation between cloud and local inference

---

## 🚧 Future Enhancements (Planned)

* Agent memory system (long-term embeddings per room)
* Personality evolution over time
* Agent-to-agent “relationship graph”
* Emotion simulation layer
* Room moderation tools for admins
* Plug-in system for custom agent behaviors

---
