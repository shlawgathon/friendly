# Friendly — Implementation Plan (v2)

Build a social network discovery app that ingests multimodal data (Instagram + voice) to construct a semantic interest graph, enabling users to find friends with shared passions.

## Resolved Items

- ✅ **Neo4j**: Docker-based local instance (no cloud needed)
- ✅ **Instagram Scraper**: Confirmed live at `localhost:8090` (uptime: 1426s)
- ✅ **Pioneer API**: Verified via Context7 — uses `gliner2` Python SDK with `GLiNER2.from_api()` + `PIONEER_API_KEY` env var
- ✅ **Yutori**: Using both **Research API** (`/v1/research/tasks`) and **Scouting API** (`/v1/scouting/tasks`)

---

## Proposed Changes

### Backend — FastAPI + Python (uv)

#### [NEW] [backend/](file:///Users/xiao/friendly/backend/)

```
backend/
├── pyproject.toml
├── .env
├── docker-compose.yml       # Neo4j + backend services
├── app/
│   ├── main.py              # FastAPI app, CORS, routers
│   ├── config.py            # pydantic-settings
│   ├── db/
│   │   ├── neo4j.py         # Neo4j Bolt driver (neo4j://localhost:7687)
│   │   └── schema.py        # Cypher constraints + indexes
│   ├── services/
│   │   ├── scraper.py       # POST localhost:8090/scrape/instagram
│   │   ├── modulate.py      # Velma-2 batch STT
│   │   ├── reka.py          # Multimodal chat (image analysis + icebreakers)
│   │   ├── pioneer.py       # GLiNER2 NER via Python SDK
│   │   ├── yutori.py        # Research + Scouting APIs
│   │   └── graph.py         # Neo4j graph queries
│   └── routers/
│       ├── ingest.py        # /api/ingest/instagram, /api/ingest/voice
│       ├── discover.py      # /api/discover/matches, /api/discover/graph
│       └── chat.py          # /api/chat/icebreaker
```

#### API Integration Details (Doc-Verified)

| Sponsor | SDK / Endpoint | Auth | Usage |
|---------|---------------|------|-------|
| **Modulate** | `POST modulate-developer-apis.com/api/velma-2-stt-batch` | `X-API-Key: {key}` header | Transcribe voice (multipart: `upload_file`, `speaker_diarization`, `emotion_signal`) |
| **Reka** | `reka-api` Python SDK: `client.chat.create(messages=[...], model="reka-flash")` | `Reka(api_key=...)` | Analyze images via `image_url` content type; generate icebreakers |
| **Pioneer** | `gliner2` Python SDK: `GLiNER2.from_api()` → `extractor.extract_entities(text, labels)` | `PIONEER_API_KEY` env var | Zero-shot NER: extract `["hobby", "location", "brand", "activity", "food", "sport"]` |
| **Yutori Research** | `POST api.yutori.com/v1/research/tasks` | `X-API-Key: {key}` header | One-time deep research on extracted interests (body: `query`, `output_schema`, `webhook_url`) |
| **Yutori Scouting** | `POST api.yutori.com/v1/scouting/tasks` | `X-API-Key: {key}` header | Ongoing monitoring for trending topics in user's interest areas (body: `query`, `output_interval` ≥1800s, `output_schema`) |
| **Scraper** | `POST localhost:8090/scrape/instagram` | None | `{"username": "...", "maxPosts": 50, "includeReels": true}` |

#### Neo4j Docker Setup

```yaml
# docker-compose.yml
services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"  # Browser
      - "7687:7687"  # Bolt
    environment:
      NEO4J_AUTH: neo4j/friendly_dev_password
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - neo4j_data:/data
volumes:
  neo4j_data:
```

#### Graph Schema

```cypher
-- Nodes
(:User {id, username, full_name, bio, profile_pic_url, created_at})
(:Hobby {name, category})
(:Location {name, type})  -- city, country, venue
(:Brand {name})
(:Activity {name})

-- Relationships
(:User)-[:INTERESTED_IN {weight: 0.0-1.0, source: 'visual'|'voice'|'bio', evidence: "..."}]->(:Hobby)
(:User)-[:VISITED {source: 'visual'}]->(:Location)
(:User)-[:FOLLOWS {source: 'visual'}]->(:Brand)
(:User)-[:CONNECTED_TO {affinity: 0.0-1.0, shared_interests: [...]}]->(:User)
```

#### Pipeline Flows

**Instagram Ingestion:**
1. **Scraper** → `POST localhost:8090/scrape/instagram` → get posts/reels
2. **Reka** → For each post, `client.chat.create(messages=[{content: [{type: "image_url", image_url: post.displayUrl}, {type: "text", text: "Describe the activities, hobbies, and interests visible in this image"}]}], model="reka-flash")` → descriptive captions
3. **Pioneer** → `extractor.extract_entities(caption + bio, ["hobby", "location", "brand", "activity"])` → structured entities with confidence scores
4. **Yutori Research** → For top 3 interests, `POST /v1/research/tasks` with `query: "What are the latest communities, events, and trends related to {interest}?"` + `output_schema` for structured results → enrich graph with context
5. **Yutori Scouting** → `POST /v1/scouting/tasks` with `query: "Monitor for new events, meetups, or trending content related to {interest}"`, `output_interval: 86400` → ongoing interest tracking
6. **Neo4j** → Create/merge User, Hobby, Location, Brand nodes + weighted relationships

**Voice Ingestion:**
1. **Modulate** → `POST /api/velma-2-stt-batch` with audio file (multipart) + `emotion_signal=true` → transcript with emotion metadata
2. **Pioneer** → Extract entities from transcript
3. **Neo4j** → Add entities with `source: 'voice'` + emotion context

---

### Frontend — Next.js + TypeScript + Tailwind + shadcn

#### [NEW] [frontend/](file:///Users/xiao/friendly/frontend/)

```
frontend/
├── package.json
├── src/
│   ├── app/
│   │   ├── layout.tsx              # Dark theme, Inter font
│   │   ├── page.tsx                # Landing → onboarding
│   │   └── dashboard/page.tsx      # Force graph discovery
│   ├── components/
│   │   ├── onboarding/
│   │   │   ├── instagram-sync.tsx  # Username input + sync
│   │   │   ├── voice-recorder.tsx  # Hold-to-record mic button
│   │   │   └── processing.tsx      # "Building your world..." animation
│   │   └── dashboard/
│   │       ├── force-graph.tsx     # D3.js force-directed visualization
│   │       ├── connection-panel.tsx # Shared interests + affinity paths
│   │       └── icebreaker-chat.tsx # Reka-powered conversation starter
│   └── lib/
│       └── api.ts                  # Backend client
```

**UX Flow:**
1. **Landing** → Dark glassmorphism hero, "Discover Your People" CTA
2. **Step 1** → Enter IG username → scraper + Reka + Pioneer + Yutori pipeline
3. **Step 2** → Hold mic 30s → Modulate STT + Pioneer extraction
4. **Processing** → Animated orbital particles ("Building your world...")
5. **Dashboard** → Force-directed graph: you at center, users clustered by shared niche interests, hover for "why" tooltips, click for Reka icebreaker chat

---

## Verification Plan

### Automated
```bash
# 1. Start Neo4j
cd backend && docker compose up neo4j -d

# 2. Start backend
uv run uvicorn app.main:app --port 8000
curl http://localhost:8000/health

# 3. Test Instagram pipeline (scraper must be at :8090)
curl -X POST http://localhost:8000/api/ingest/instagram \
  -H "Content-Type: application/json" \
  -d '{"username": "natgeo", "max_posts": 5}'

# 4. Start frontend
cd frontend && bun run dev  # → localhost:3000
```

### Manual
1. Full onboarding flow: enter username → see graph populate
2. Voice recording: speak 10s → verify entities extracted
3. Graph hovering: verify shared-interest tooltips
4. Click node → verify icebreaker chat with context
