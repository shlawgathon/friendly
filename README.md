# Friendly 🤝

**Automatically find friends within your close network with shared interests.**

Skip the awkward conversations and get straight into deep conversations about shared passions that go deeper than "how was your day?"

## How It Works

1. **Connect** — Sync your Instagram account
2. **Analyze** — AI analyzes your posts, captions, and bio to map your interests
3. **Discover** — See a visual graph of your interests and find people who share them
4. **Connect** — Get AI-generated icebreakers for shared interests

## Tech Stack

### Frontend

- **Next.js** + React + TypeScript
- **Tailwind CSS** + shadcn/ui
- **D3.js** force-directed graph visualization
- **Bun** runtime

### Backend

- **FastAPI** (Python)
- **Neo4j** graph database
- **[Atlas Pipeline](scraper-guide-new.md)** scraper-standalone (Instagram HTTP scraping)
- **UV** package manager

### AI Services

| Service      | Role                                                       |
| ------------ | ---------------------------------------------------------- |
| **Reka**     | Image analysis, interest extraction, icebreaker generation |
| **Yutori**   | Research & scouting tasks for interest enrichment          |
| **Modulate** | Speech-to-text for voice ingestion                         |

## Getting Started

### Prerequisites

- Node.js 18+ / Bun
- Python 3.11+
- Docker (for Neo4j)

### Setup

```bash
# Clone
git clone https://github.com/shlawgathon/friendly.git
cd friendly

# Backend
cd backend
cp .env.example .env  # Add your API keys
uv sync
source .venv/bin/activate
uvicorn app.main:app --port 8000 --reload

# Frontend (new terminal)
cd frontend
bun install
bun run dev
```

### Neo4j

```bash
# Local (Docker)
docker compose up neo4j -d

# Or use Neo4j Aura (cloud) — update NEO4J_URI in .env
```

### Environment Variables

```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# AI Services
REKA_API_KEY=your_key
YUTORI_API_KEY=your_key
MODULATE_API_KEY=your_key
PIONEER_API_KEY=your_key

# Scraper Standalone
SCRAPER_URL=http://localhost:8090
SCRAPER_API_KEY=your_key
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend   │────▶│   Backend   │────▶│   Neo4j     │
│  Next.js     │     │   FastAPI   │     │   Graph DB  │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────┼──────┐
                    ▼      ▼      ▼
                  Reka  Yutori  Modulate
```

### Ingestion Pipeline

1. **Scrape** — scraper-standalone fetches profile, posts, and reels via Instagram's internal APIs
2. **Analyze** — Reka vision analyzes each image with post caption context
3. **Extract** — Reka extracts structured interests (hobbies, brands) from combined text
4. **Store** — Entities written to Neo4j as `User → INTERESTED_IN → Hobby` / `User → FOLLOWS → Brand`
5. **Enrich** — Yutori submits research & scouting tasks for top interests

## License

MIT
