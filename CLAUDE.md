# CLAUDE.md — Friendly 3-Tier Enrichment Microservices

## Project Overview

Two microservices that add **Tier 2 (Browsing)** and **Tier 3 (n1 Deep)** enrichment on top of the existing Friendly base pipeline. These sit alongside the main backend and write enrichment data into the shared Neo4j graph.

**Repo root:** `friendly/`
**These microservices live at:** `friendly/enrichment/`

```
friendly/
├── backend/                    # Existing main backend (:8000) — Tier 1
├── frontend/                   # Existing Next.js frontend (:3000)
└── enrichment/                 # NEW — this project
    ├── CLAUDE.md               # You are here
    ├── start.sh                # Boot script for both services
    ├── browsing-service/       # Tier 2 (:8001)
    └── n1-service/             # Tier 3 (:8002)
```

---

## Architecture — 3 Enrichment Tiers

```
┌─────────────────────────────────────────────────────────────────┐
│                    Main Backend (:8000)                          │
│                                                                 │
│  Scraper (:8090) → Reka Vision → Pioneer NER → Yutori Research │
│                                                                 │
│  🟢 TIER 1 — BASE                                               │
│  Produces: User, Hobby, Location, Brand nodes                   │
│  Relationships: INTERESTED_IN, VISITED, FOLLOWS                 │
└───────────────────────┬─────────────────────────────────────────┘
                        │
          ┌─────────────┼─────────────────┐
          │                               │
          ▼                               ▼
┌─────────────────────────┐  ┌─────────────────────────────────┐
│ Browsing Service (:8001)│  │ n1 Service (:8002)              │
│                         │  │                                 │
│ Yutori Browsing API     │  │ Yutori n1 API + Playwright      │
│ (cloud browser agents)  │  │ (local headless browser)        │
│                         │  │                                 │
│ • Eventbrite → events   │  │ • IG highlight navigation       │
│ • Reddit → communities  │  │ • Deep scroll history           │
│ • Meetup → local groups │  │ • Vibe fingerprinting           │
│ • Profile URL scraping  │  │ • Visual profile comparison     │
│                         │  │                                 │
│ 🟡 TIER 2 — CONTEXTUAL  │  │ 🔴 TIER 3 — DEEP                │
│ Adds: Event, Community, │  │ Adds: DeepInsight, VibeProfile  │
│       Meetup nodes       │  │       SIMILAR_VIBE relationships│
└─────────────────────────┘  └─────────────────────────────────┘
```

| Tier | Service | Port | Latency | What It Adds |
|------|---------|------|---------|-------------|
| 1 — Base | Main backend | 8000 | ~5s | Interests, locations, brands from posts + bio |
| 2 — Contextual | Browsing service | 8001 | ~15-30s | Events, communities, meetups for each interest |
| 3 — Deep | n1 service | 8002 | ~30-60s | Stories/highlights, deeper post history, vibe scores |

Tiers are **additive** — Tier 3 includes everything from Tiers 1 and 2.

---

## Integration Points

### WHERE TO CALL THESE SERVICES

The main backend orchestrates all tiers. The call sites are in the **ingest router**.

**File:** `backend/app/routers/ingest.py`
**Function:** The Instagram ingestion endpoint
**When:** After Pioneer NER extraction completes and base graph nodes are written

```python
# backend/app/routers/ingest.py
#
# INTEGRATION POINT — Add tier parameter to the ingest request model
# and call enrichment services after base pipeline completes.

from pydantic import BaseModel, Field
import httpx

class IngestRequest(BaseModel):
    username: str
    max_posts: int = 50
    enrichment_tier: int = Field(default=1, ge=1, le=3)  # NEW FIELD


@router.post("/api/ingest/instagram")
async def ingest_instagram(req: IngestRequest):
    # ── Tier 1 — Base (always runs) ─────────────────────────────
    posts = await scraper.scrape(req.username, req.max_posts)
    captions = await reka.analyze_posts(posts)
    entities = await pioneer.extract(captions)
    location = next((e["text"] for e in entities if e["label"] == "location"), None)
    interests = [e["text"] for e in entities if e["label"] in ("hobby", "activity", "sport")]
    await graph.write_base(req.username, entities)

    # ── Tier 2 — Contextual Enrichment ──────────────────────────
    # INTEGRATION POINT: Call browsing-service after base graph is written
    if req.enrichment_tier >= 2:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post("http://localhost:8001/api/enrich/browse", json={
                "username": req.username,
                "interests": interests[:3],
                "location": location,
            })

    # ── Tier 3 — Deep Enrichment ────────────────────────────────
    # INTEGRATION POINT: Call n1-service after browsing enrichment
    if req.enrichment_tier >= 3:
        async with httpx.AsyncClient(timeout=120) as client:
            await client.post("http://localhost:8002/api/enrich/deep", json={
                "username": req.username,
                "instagram_url": f"https://instagram.com/{req.username}",
                "interests": interests[:3],
                "max_highlights": 3,
                "scroll_depth": 20,
            })

    return {"status": "ok", "username": req.username, "tier": req.enrichment_tier}
```

### WHERE THE FRONTEND TRIGGERS TIERS

**File:** `frontend/src/components/onboarding/instagram-sync.tsx`
**When:** User submits their IG username during onboarding

```typescript
// frontend/src/lib/api.ts
//
// INTEGRATION POINT: Add enrichment_tier to the ingest call.
// Default to tier 2 for onboarding. Tier 3 can be triggered
// from the dashboard as a "Deep Scan" button.

export async function ingestInstagram(username: string, tier: number = 2) {
  return fetch("/api/ingest/instagram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      max_posts: 50,
      enrichment_tier: tier,
    }),
  });
}

// Dashboard "Deep Scan" button triggers Tier 3 for a specific match
export async function deepScanProfile(username: string, igUrl: string) {
  return fetch("http://localhost:8002/api/enrich/deep", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      instagram_url: igUrl,
      max_highlights: 3,
      scroll_depth: 20,
    }),
  });
}
```

**File:** `frontend/src/components/dashboard/connection-panel.tsx`
**When:** User clicks on a matched user node and wants vibe comparison

```typescript
// INTEGRATION POINT: Vibe comparison between two users
export async function compareVibes(userA: string, userB: string, igUrlA: string, igUrlB: string) {
  return fetch("http://localhost:8002/api/enrich/vibe-compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username_a: userA,
      username_b: userB,
      instagram_url_a: igUrlA,
      instagram_url_b: igUrlB,
    }),
  });
}
```

### WHERE ENRICHMENT DATA SHOWS UP IN THE GRAPH QUERY

**File:** `backend/app/services/graph.py`
**Function:** The match discovery query that powers the force graph

```cypher
-- INTEGRATION POINT: Update the match query to include Tier 2 + 3 data
--
-- Current query (Tier 1 only):
-- MATCH (u:User {username: $username})-[:INTERESTED_IN]->(h:Hobby)<-[:INTERESTED_IN]-(other:User)
-- RETURN other, collect(h) as shared
--
-- Updated query (all tiers):
MATCH (u:User {username: $username})-[:INTERESTED_IN]->(h:Hobby)<-[:INTERESTED_IN]-(other:User)
WITH u, other, collect(DISTINCT h.name) AS shared_interests

-- Tier 2: shared events/communities
OPTIONAL MATCH (u)-[:ENRICHED_VIA]->(e:Event)<-[:ENRICHED_VIA]-(other)
WITH u, other, shared_interests, collect(DISTINCT e.title) AS shared_events

OPTIONAL MATCH (u)-[:ENRICHED_VIA]->(c:Community)<-[:ENRICHED_VIA]-(other)
WITH u, other, shared_interests, shared_events, collect(DISTINCT c.name) AS shared_communities

-- Tier 3: vibe similarity
OPTIONAL MATCH (u)-[:HAS_VIBE]->(v1:VibeProfile)-[sv:SIMILAR_VIBE]->(v2:VibeProfile)<-[:HAS_VIBE]-(other)
WITH u, other, shared_interests, shared_events, shared_communities,
     sv.score AS vibe_score, sv.shared_aesthetics AS shared_aesthetics

RETURN other.username AS username,
       other.full_name AS full_name,
       other.profile_pic_url AS pic,
       shared_interests,
       shared_events,
       shared_communities,
       vibe_score,
       shared_aesthetics,
       (size(shared_interests) * 0.4 +
        size(shared_events) * 0.2 +
        size(shared_communities) * 0.1 +
        coalesce(vibe_score, 0) * 0.3) AS affinity_score
ORDER BY affinity_score DESC
LIMIT 20
```

---

## Browsing Service (Tier 2)

### Directory Structure

```
enrichment/browsing-service/
├── pyproject.toml
├── .env                         # Copy from .env.example, add YUTORI_API_KEY
├── .env.example
└── app/
    ├── main.py                  # FastAPI app on :8001
    ├── config.py                # pydantic-settings (YUTORI_API_KEY, NEO4J_*)
    ├── db/
    │   └── neo4j.py             # Async Neo4j driver singleton
    ├── models/
    │   └── enrichment.py        # Request/response Pydantic models
    ├── routers/
    │   └── enrich.py            # POST /api/enrich/browse, POST /api/enrich/profile
    └── services/
        ├── browsing.py          # Yutori Browsing API client
        └── graph_writer.py      # Writes Event, Community, Meetup nodes to Neo4j
```

### Endpoints

**`POST /api/enrich/browse`** — Main enrichment endpoint
```json
{
  "username": "natgeo",
  "interests": ["photography", "wildlife", "travel"],
  "location": "San Francisco"
}
```
For each interest (capped at 3), dispatches parallel Yutori Browsing tasks:
- Eventbrite → find upcoming events
- Reddit → find active communities
- Meetup → find local groups (if location provided)

**`POST /api/enrich/profile`** — Profile URL extraction
```json
{
  "username": "natgeo",
  "url": "https://linkedin.com/in/some-profile"
}
```
Extracts name, headline, interests, social links from a public profile URL found in IG bio.

**`GET /health`** → `{"status": "ok", "service": "browsing-enrichment", "tier": 2}`

### How It Works

1. Receives interests + location from main backend
2. Constructs natural language task prompts for Yutori Browsing API
3. `POST https://api.yutori.com/v1/browsing/tasks` with task description + `output_schema`
4. Polls `GET /v1/browsing/tasks/{id}` every 3s until completed (120s timeout)
5. Runs all tasks in parallel via `asyncio.gather`
6. Writes results to Neo4j: `(:Hobby)-[:HAS_EVENT]->(:Event)`, `(:Hobby)-[:HAS_COMMUNITY]->(:Community)`, etc.

### API Details — Yutori Browsing

```python
# POST https://api.yutori.com/v1/browsing/tasks
# Headers: X-API-Key: {YUTORI_API_KEY}, Content-Type: application/json
#
# Body:
{
    "task": "Go to eventbrite.com and search for 'photography' events near 'San Francisco'. Return top 3 with title, date, location, url, description as JSON.",
    "output_schema": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string"},
                "url": {"type": "string"}
            },
            "required": ["title", "date", "url"]
        }
    }
}
#
# Response: {"id": "task_xxx", "status": "pending"}
# Poll GET /v1/browsing/tasks/task_xxx until status == "completed"
# Completed response includes "output" field with structured data
```

For login-heavy flows, set `"require_auth": true` to use auth-optimized browser.

### Neo4j Nodes & Relationships Created

```cypher
(:Event {title, date, location, url, description, source: 'browsing'})
(:Community {name, subscriber_count, description, url, source: 'browsing'})
(:Meetup {name, date, location, url, attendees, source: 'browsing'})

(:Hobby)-[:HAS_EVENT]->(:Event)
(:Hobby)-[:HAS_COMMUNITY]->(:Community)
(:Hobby)-[:HAS_MEETUP]->(:Meetup)
(:User)-[:ENRICHED_VIA {type: 'event'|'community'|'meetup', tier: 2}]->(:Event|:Community|:Meetup)
```

### Dependencies

```toml
# pyproject.toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "httpx>=0.27.0",
    "neo4j>=5.20.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]
```

---

## n1 Service (Tier 3)

### Directory Structure

```
enrichment/n1-service/
├── pyproject.toml
├── .env                         # YUTORI_API_KEY, REKA_API_KEY, NEO4J_*
├── .env.example
└── app/
    ├── main.py                  # FastAPI app on :8002
    ├── config.py                # pydantic-settings
    ├── db/
    │   └── neo4j.py             # Async Neo4j driver singleton
    ├── models/
    │   └── enrichment.py        # DeepEnrichRequest/Response, VibeFingerprint, etc.
    ├── routers/
    │   └── enrich.py            # POST /api/enrich/deep, POST /api/enrich/vibe-compare
    └── services/
        ├── browser_agent.py     # Playwright + n1 agent loop
        ├── vision.py            # Reka screenshot analysis + vibe fingerprinting
        ├── orchestrator.py      # Ties browser + vision + graph together
        └── graph_writer.py      # Writes DeepInsight, VibeProfile to Neo4j
```

### Endpoints

**`POST /api/enrich/deep`** — Full deep enrichment
```json
{
  "username": "natgeo",
  "instagram_url": "https://instagram.com/natgeo",
  "interests": ["photography", "wildlife"],
  "max_highlights": 3,
  "scroll_depth": 20
}
```
Launches a headless browser, navigates the IG profile with n1, captures screenshots, analyzes with Reka, generates vibe fingerprint, writes to Neo4j.

**`POST /api/enrich/vibe-compare`** — Compare two profiles
```json
{
  "username_a": "natgeo",
  "username_b": "beautifuldestinations",
  "instagram_url_a": "https://instagram.com/natgeo",
  "instagram_url_b": "https://instagram.com/beautifuldestinations"
}
```
Returns similarity score + shared aesthetics + shared themes.

**`GET /health`** → `{"status": "ok", "service": "deep-enrichment", "tier": 3}`

### How It Works — The n1 Agent Loop

n1 is a pixels-to-actions LLM. It follows the OpenAI Chat Completions interface. The loop:

```
┌──────────┐     screenshot     ┌──────────┐     action      ┌──────────┐
│ Playwright│ ──────────────────→│  n1 API  │ ──────────────→│ Playwright│
│ (browser) │ ←──── execute ────│ (predict)│                 │ (execute)│
└──────────┘                    └──────────┘                 └──────────┘
     │                                                            │
     └────────────── repeat until n1 says "done" ────────────────┘
```

1. Take screenshot of current browser state → base64 PNG
2. Send to n1: instruction + screenshot + last 5 action history
3. n1 returns: `{"action": "click", "params": {"x": 450, "y": 300}, "reasoning": "clicking highlight circle"}`
4. Execute action in Playwright
5. Repeat (max 15 steps per task)

### API Details — Yutori n1

```python
# POST https://api.yutori.com/v1/chat/completions
# Headers: X-API-Key: {YUTORI_API_KEY}, Content-Type: application/json
#
# Follows OpenAI Chat Completions interface:
{
    "model": "n1",
    "max_tokens": 500,
    "messages": [
        {
            "role": "system",
            "content": "You are a browser automation agent. Given a screenshot and instruction, predict the next action. Respond with JSON: {action, params, reasoning}."
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,{screenshot}"}
                },
                {
                    "type": "text",
                    "text": "Instruction: Click on highlight circle #1 on this Instagram profile."
                },
                {
                    "type": "text",
                    "text": "Previous actions:\nStep 1: click — dismissed cookie banner"
                }
            ]
        }
    ]
}
#
# Response follows OpenAI format:
# data.choices[0].message.content = '{"action": "click", "params": {"x": 450, "y": 300}, "reasoning": "..."}'
#
# Supported actions: click, type, scroll, press, wait, done
```

### Pipeline — Deep Enrichment

```
1. create_browser()           → Playwright Chromium (headless)
2. navigate_ig_profile()      → n1 agent loop:
   a. Load profile URL
   b. Dismiss modals (n1 loop, max 3 steps)
   c. Screenshot profile header
   d. For each highlight (max 3):
      - n1 clicks highlight circle
      - Capture screenshot
      - n1 closes overlay
   e. Scroll through posts (scroll_depth / 5 batches)
      - Capture screenshot per batch
3. extract_interests()        → Send screenshots to Reka:
   - "Describe activities, hobbies, interests visible"
   - Parse JSON response for interest list
4. generate_vibe_fingerprint()→ Send representative screenshots to Reka:
   - aesthetic_tags: ["minimalist", "outdoor", "warm tones"]
   - color_palette: ["earth tones", "blues"]
   - mood: "adventurous"
   - energy: 0.0 (calm) → 1.0 (energetic)
   - content_themes: ["travel", "food", "fitness"]
5. write_deep_enrichments()   → Neo4j:
   - Create DeepInsight nodes
   - Create VibeProfile node
   - Compute SIMILAR_VIBE relationships with all existing VibeProfiles
   - Add new INTERESTED_IN relationships for discovered interests
```

### Vibe Similarity Computation

Done both in Python (for API response) and in Cypher (for graph persistence):

```
score = (tag_overlap * 0.3) + (theme_overlap * 0.3) + (energy_closeness * 0.2) + (mood_match * 0.2)
```

Only persists `SIMILAR_VIBE` edges where score > 0.3.

### Neo4j Nodes & Relationships Created

```cypher
(:DeepInsight {type: 'highlight'|'deep_post', content, source_url, interests_found, source: 'n1', tier: 3})
(:VibeProfile {username, aesthetic_tags, color_palette, mood, energy, content_themes, source: 'n1'})

(:User)-[:HAS_INSIGHT]->(:DeepInsight)
(:User)-[:HAS_VIBE]->(:VibeProfile)
(:VibeProfile)-[:SIMILAR_VIBE {score, shared_aesthetics, shared_themes}]->(:VibeProfile)
(:User)-[:INTERESTED_IN {weight: 0.4, source: 'n1_deep', evidence: '...'}]->(:Hobby)
```

### Dependencies

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "httpx>=0.27.0",
    "neo4j>=5.20.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "playwright>=1.40.0",
    "reka-api>=3.0.0",
]
```

After `uv sync`, run `uv run playwright install chromium` to install the browser.

---

## Environment Variables

Both services share the same Neo4j instance. Create `.env` in each service directory.

### browsing-service/.env
```
YUTORI_API_KEY=           # Required — Yutori API key
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=friendly_dev_password
LOG_LEVEL=INFO
```

### n1-service/.env
```
YUTORI_API_KEY=           # Required — Yutori API key
REKA_API_KEY=             # Required — Reka API key (for screenshot analysis)
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=friendly_dev_password
HEADLESS=true             # Set false to watch the browser during demos
SCREENSHOT_DIR=/tmp/friendly-screenshots
LOG_LEVEL=INFO
N1_MODEL=n1
N1_BASE_URL=https://api.yutori.com/v1
```

---

## Running

### Prerequisites
- Neo4j running via `docker compose up neo4j -d` (from `backend/docker-compose.yml`)
- Instagram scraper running at `:8090`
- Main backend running at `:8000`
- `uv` installed

### Start Both Services
```bash
cd enrichment
./start.sh        # Both services
./start.sh 2      # Only Tier 2
./start.sh 3      # Only Tier 3
```

### Start Individually
```bash
# Tier 2
cd enrichment/browsing-service
cp .env.example .env   # Add YUTORI_API_KEY
uv sync
uv run uvicorn app.main:app --port 8001 --reload

# Tier 3
cd enrichment/n1-service
cp .env.example .env   # Add YUTORI_API_KEY + REKA_API_KEY
uv sync
uv run playwright install chromium
uv run uvicorn app.main:app --port 8002 --reload
```

### Health Checks
```bash
curl http://localhost:8001/health   # Tier 2
curl http://localhost:8002/health   # Tier 3
```

### Test Calls
```bash
# Tier 2 — Browsing enrichment
curl -X POST http://localhost:8001/api/enrich/browse \
  -H "Content-Type: application/json" \
  -d '{"username": "natgeo", "interests": ["photography", "wildlife"], "location": "San Francisco"}'

# Tier 3 — Deep enrichment
curl -X POST http://localhost:8002/api/enrich/deep \
  -H "Content-Type: application/json" \
  -d '{"username": "natgeo", "instagram_url": "https://instagram.com/natgeo", "interests": ["photography"], "max_highlights": 3, "scroll_depth": 20}'

# Tier 3 — Vibe comparison
curl -X POST http://localhost:8002/api/enrich/vibe-compare \
  -H "Content-Type: application/json" \
  -d '{"username_a": "natgeo", "username_b": "beautifuldestinations", "instagram_url_a": "https://instagram.com/natgeo", "instagram_url_b": "https://instagram.com/beautifuldestinations"}'
```

---

## Complete Neo4j Schema (All Tiers)

```cypher
-- ═══ TIER 1 (base) ═══
CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.username IS UNIQUE;
CREATE CONSTRAINT hobby_name IF NOT EXISTS FOR (h:Hobby) REQUIRE h.name IS UNIQUE;
CREATE CONSTRAINT brand_name IF NOT EXISTS FOR (b:Brand) REQUIRE b.name IS UNIQUE;

(:User {id, username, full_name, bio, profile_pic_url, created_at})
(:Hobby {name, category})
(:Location {name, type})
(:Brand {name})
(:Activity {name})

(:User)-[:INTERESTED_IN {weight: 0.0-1.0, source: 'visual'|'voice'|'bio', evidence}]->(:Hobby)
(:User)-[:VISITED {source}]->(:Location)
(:User)-[:FOLLOWS {source}]->(:Brand)
(:User)-[:CONNECTED_TO {affinity: 0.0-1.0, shared_interests}]->(:User)

-- ═══ TIER 2 (browsing) ═══
CREATE CONSTRAINT event_url IF NOT EXISTS FOR (e:Event) REQUIRE e.url IS UNIQUE;
CREATE CONSTRAINT community_url IF NOT EXISTS FOR (c:Community) REQUIRE c.url IS UNIQUE;
CREATE CONSTRAINT meetup_url IF NOT EXISTS FOR (m:Meetup) REQUIRE m.url IS UNIQUE;

(:Event {title, date, location, url, description, source: 'browsing'})
(:Community {name, subscriber_count, description, url, source: 'browsing'})
(:Meetup {name, date, location, url, attendees, source: 'browsing'})

(:Hobby)-[:HAS_EVENT]->(:Event)
(:Hobby)-[:HAS_COMMUNITY]->(:Community)
(:Hobby)-[:HAS_MEETUP]->(:Meetup)
(:User)-[:ENRICHED_VIA {type, tier: 2}]->(:Event|:Community|:Meetup)

-- ═══ TIER 3 (n1 deep) ═══
(:DeepInsight {type, content, source_url, interests_found, source: 'n1', tier: 3})
(:VibeProfile {username, aesthetic_tags, color_palette, mood, energy, content_themes, source: 'n1'})

(:User)-[:HAS_INSIGHT]->(:DeepInsight)
(:User)-[:HAS_VIBE]->(:VibeProfile)
(:VibeProfile)-[:SIMILAR_VIBE {score: 0.0-1.0, shared_aesthetics, shared_themes}]->(:VibeProfile)
(:User)-[:INTERESTED_IN {weight: 0.4, source: 'n1_deep', evidence}]->(:Hobby)
```

---

## Demo Tips

- **Default onboarding to Tier 2** — fast enough (~15-30s) and gives great results for the graph
- **Tier 3 as a "Deep Scan" button** on the dashboard — shows the n1 agent navigating in real-time if `HEADLESS=false`
- **Vibe comparison** is the wow factor — click two user nodes and show their aesthetic similarity
- **Processing animation** should show tier progression: "Analyzing posts..." → "Finding events & communities..." → "Deep scanning profile..."
- The force graph tooltip for Tier 2 matches: "You both might enjoy SF Photography Meetup this Saturday"
- The force graph tooltip for Tier 3 matches: "You share an adventurous, earth-toned aesthetic"


Yutori Docs: https://docs.yutori.com/