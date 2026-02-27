# Atlas Pipeline

Instagram/TikTok data-ingestion backbone for [TrendSweep](https://trendsweep.com). Discovers creators, scrapes profiles and posts, downloads media to GCS, runs Gemini AI analysis, generates vector embeddings, and upserts them into Qdrant for semantic search.

## VM Command:

```
gcloud compute ssh --zone "us-central1-f" "trendsweep-us-central1-1" --project "trendsweep-pipeline"
```

## How It Works

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                       Docker Compose                             │
 │                                                                  │
 │  redis:7 ◄────────────── pipeline (Bun)                         │
 │  (BullMQ)                  │                                     │
 │                 ┌──────────┼──────────┐                          │
 │                 ▼          ▼          ▼                          │
 │           Schedulers    Workers    Bull Board                    │
 │          (repeatable)  (9 total)  /admin/queues                  │
 │                 │                                                │
 │    enrich-tick ─┤                                                │
 │    batch-submit │──► enrich-creator ──► creator-upsert           │
 │    batch-poll   │──► analyze-video      media-download           │
 │    synthesis     ──► batch-poller       embed-video              │
 │                     synthesize-creator  embed-creator            │
 │                     refresh-payload                              │
 │                          │                                       │
 │  scraper-standalone ◄────┘ (POST /scrape/instagram)             │
 │  (IG + TikTok scraper)     (POST /scrape/tiktok)                │
 └───────────────────────┬──────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     PostgreSQL       Qdrant          GCS
     (profiles,     (vectors,      (videos,
      posts,         search)       thumbnails,
      analyses)                    raw JSON)
```

VM: gcloud compute ssh --zone "us-central1-f" "trendsweep-us-central1-1" --project "trendsweep-pipeline"

### What actually scrapes?

**scraper-standalone** does the real scraping. It handles both Instagram and TikTok:

**Instagram** — hits Instagram's undocumented internal APIs directly:

| Endpoint                                         | What it fetches                                                                    |
| ------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `i.instagram.com/api/v1/users/web_profile_info/` | Profile data (bio, followers, first ~12 posts)                                     |
| `instagram.com/graphql/query` (GET)              | Paginated posts via XDT GraphQL (username + cursor)                                |
| `instagram.com/graphql/query` (GET)              | Reels via XDT GraphQL (falls back to posts doc_id + `product_type='clips'` filter) |

Requests go through **residential proxies** (migrating from Apify to [StatProxies](https://statproxies.com) flat-rate) using [`impit`](https://github.com/nicbarker/impit) for browser-like TLS fingerprinting. Starts on datacenter proxies (cheap), auto-escalates to residential on 403. Rate limiting (150 req/hr token bucket), session rotation, and retry logic keep it from getting blocked.

**TikTok** — dual approach:

| Method                                         | What it fetches                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------------------ |
| `impit` + HTML rehydration                     | Profile data (bio, followers, stats) from `__UNIVERSAL_DATA_FOR_REHYDRATION__` |
| [OnKernel](https://onkernel.com) cloud browser | Video list via Playwright script intercepting `/api/post/item_list/`           |

### Pipeline Components

| Component              | What it does                                                                            | Runtime          |
| :--------------------- | :-------------------------------------------------------------------------------------- | :--------------- |
| **scraper-standalone** | Instagram + TikTok scraper — REST + GraphQL APIs through Apify proxies, Kernel browsers | Node.js (Docker) |
| **pipeline**           | BullMQ-based job runner — 9 workers, 4 schedulers, Bull Board dashboard                 | Bun (Docker)     |
| **redis**              | Job queue storage for BullMQ — internal-only, password-protected                        | Docker           |
| **workers/shared**     | Shared types, DB schema (Drizzle), Gemini/Qdrant clients, scraper provider              | Library          |

#### Pipeline Workers

| Worker                 | Queue                | What it does                                                       |
| :--------------------- | :------------------- | :----------------------------------------------------------------- |
| **enrich-creator**     | `enrich-creator`     | Tick: fetch pending creators. Job: scrape via provider chain → R2  |
| **analyze-video**      | `analyze-video`      | Tick: submit pending videos as Gemini batch. Job: sync fallback    |
| **batch-poller**       | `batch-poller`       | Tick: poll Gemini batch jobs, process completed results            |
| **synthesize-creator** | `synthesize-creator` | Tick: find synthesis-ready creators. Job: aggregate → Gemini       |
| **creator-upsert**     | `creator-upsert`     | Upsert creator + posts to Postgres, chain to refresh-payload       |
| **media-download**     | `media-download`     | Download CDN media → upload to R2 via S3-compat, update DB refs    |
| **embed-video**        | `embed-video`        | Generate embeddings per analysis dimension → Qdrant + DB reference |
| **embed-creator**      | `embed-creator`      | Generate creator profile embeddings → Qdrant + DB reference        |
| **refresh-payload**    | `refresh-payload`    | Update Qdrant point payloads with latest DB metadata               |

### Where data is stored

| Store                              | What                                                                      | Access via                  |
| :--------------------------------- | :------------------------------------------------------------------------ | :-------------------------- |
| **PlanetScale Metal** (PostgreSQL) | Profiles, posts, analyses, embeddings — uses `dev` branch for development | `postgres` driver (Drizzle) |
| **Google Cloud Storage (GCS)**     | Videos, thumbnails, profile pics, raw JSON                                | GCS SDK / S3-compat         |
| **Qdrant**                         | Vector embeddings for semantic search                                     | REST API                    |
| **Redis**                          | BullMQ job queues, schedulers state                                       | `bullmq` library            |

> **Migration note:** Previously used Cloudflare R2 for object storage. Moving to GCS since the pipeline VM runs on GCP — eliminates cross-cloud egress costs.

The DB is shared with the Next.js app (`trendsweep-b2b`). Schema lives in `workers/shared/src/pipeline-schema.ts` (Drizzle ORM).

## Repo Structure

```
atlas-pipeline/
├── scraper-standalone/    # Instagram + TikTok scraper (Node.js + Docker)
│   ├── src/
│   │   ├── index.ts       # Hono HTTP server — /scrape/instagram, /scrape/tiktok
│   │   ├── instagram/
│   │   │   ├── client.ts  # HTTP client (impit, proxy escalation, rate limiter, retries)
│   │   │   ├── scrape.ts  # Orchestrator — profile fetch + GraphQL pagination
│   │   │   ├── posts.ts   # GraphQL pagination (fetchAllPosts, fetchReels)
│   │   │   ├── config.ts  # GraphQL doc IDs (expire every 2-4 weeks)
│   │   │   ├── proxy.ts   # Apify proxy builder + datacenter cooldown
│   │   │   ├── rate-limiter.ts # Token bucket (150 req/hr)
│   │   │   ├── errors.ts  # Custom error classes
│   │   │   ├── types.ts   # IG API response types + clean output types
│   │   │   └── discovery/ # Playwright script to discover new doc_ids
│   │   └── tiktok/
│   │       ├── client.ts  # TikTok HTML fetcher (impit + residential proxy)
│   │       ├── scrape.ts  # Orchestrator — profile + videos
│   │       ├── parser.ts  # HTML → __UNIVERSAL_DATA_FOR_REHYDRATION__ extractor
│   │       ├── videos.ts  # OnKernel cloud browser → Playwright video intercept
│   │       ├── proxy.ts   # Apify residential proxy session management
│   │       ├── errors.ts  # Custom error classes
│   │       └── types.ts   # TikTok data types
│   ├── Dockerfile
│   ├── package.json
│   └── .env.example
├── pipeline/              # BullMQ pipeline service (Bun + Docker)
│   ├── src/
│   │   ├── index.ts       # Entrypoint — boots workers, schedulers, HTTP
│   │   ├── config.ts      # Redis connection + environment variables
│   │   ├── db.ts          # Drizzle ORM + postgres client
│   │   ├── queues.ts      # 9 named BullMQ queues
│   │   ├── scheduler.ts   # 4 repeatable job schedulers
│   │   ├── server.ts      # Hono HTTP + Bull Board dashboard
│   │   └── workers/       # 9 worker files (one per queue)
│   ├── Dockerfile
│   ├── package.json
│   └── .env.example
├── workers/
│   ├── shared/            # Shared types, DB schema, API clients
│   ├── scheduler/         # (legacy) Cloudflare Worker — replaced by pipeline
│   ├── crawler/           # (legacy) Cloudflare Worker — replaced by pipeline
│   ├── analyzer/          # (legacy) Cloudflare Worker — replaced by pipeline
│   ├── db-writer/         # (legacy) Cloudflare Worker — replaced by pipeline
│   └── ingest/            # (legacy) Cloudflare Worker — replaced by pipeline
├── miami-v2/              # (deprecated) IG-only scraper — replaced by scraper-standalone
├── docker-compose.yml     # redis + pipeline + scraper-standalone
├── scripts/               # Local maintenance scripts
└── .github/workflows/     # CI/CD
```

## Setup

### Prerequisites

- [Bun](https://bun.sh) (v1.2+) — pipeline runtime
- [Node.js](https://nodejs.org) (v22+) — scraper-standalone runtime
- [Docker](https://docs.docker.com/get-docker/) or [OrbStack](https://orbstack.dev) — running services

### 1. Install dependencies

```bash
git clone https://github.com/TrendSweep/atlas-pipeline.git
cd atlas-pipeline

# Scraper standalone
cd scraper-standalone && npm install

# Pipeline (if developing locally)
cd ../pipeline && bun install
```

### 2. Environment variables

**scraper-standalone** — create `scraper-standalone/.env`:

```env
# Required — Apify proxy for IG + TikTok profile scraping
APIFY_PROXY_PASSWORD=your_apify_proxy_password

# Required for TikTok video scraping — OnKernel cloud browser
KERNEL_API_KEY=your_kernel_api_key

# Required — bearer token auth for external callers (Vercel frontend, pipeline)
# Must match WORKER_API_KEY set in Vercel env vars
WORKER_API_KEY=any_secret_for_auth

# Optional — defaults to 8090
PORT=8090
```

**Pipeline** — copy and fill `pipeline/.env`:

```bash
cp pipeline/.env.example pipeline/.env
```

| Variable                 | Required | Where to get it                                       |
| :----------------------- | :------- | :---------------------------------------------------- |
| `REDIS_HOST`             | Yes      | `redis` (Docker) or `localhost` (local)               |
| `REDIS_PASSWORD`         | Yes      | Any strong password — must match `docker-compose.yml` |
| `DATABASE_URL`           | Yes      | PlanetScale dashboard → Connect → `dev` branch        |
| `GEMINI_API_KEY`         | Yes      | Google AI Studio — analysis + synthesis               |
| `AI_GATEWAY_API_KEY`     | Yes      | Vercel AI Gateway — embeddings only                   |
| `QDRANT_URL`             | Yes      | Qdrant Cloud dashboard                                |
| `QDRANT_API_KEY`         | Yes      | Qdrant Cloud → API Keys                               |
| `R2_ENDPOINT`            | Yes      | Cloudflare R2 → Bucket → S3 API endpoint              |
| `R2_ACCESS_KEY`          | Yes      | Cloudflare R2 → R2 API Tokens                         |
| `R2_SECRET_KEY`          | Yes      | Cloudflare R2 → R2 API Tokens                         |
| `R2_BUCKET`              | Yes      | `trendsweep-pipeline` (default)                       |
| `R2_PUBLIC_DOMAIN`       | Yes      | Public domain for R2 bucket (video URLs)              |
| `SCRAPECREATORS_API_KEY` | Yes      | ScrapeCreators dashboard                              |
| `APIFY_API_TOKEN`        | Yes      | Apify Console → Settings → Integrations               |
| `WORKER_API_KEY`         | Yes      | Must match `scraper-standalone/.env`                  |
| `BULL_BOARD_PASSWORD`    | Optional | Any string — protects `/admin/queues` dashboard       |

### 3. Run the full stack

```bash
# Docker (recommended) — starts redis + pipeline + scraper-standalone
docker compose up --build

# Pipeline at http://localhost:3000
# Bull Board at http://localhost:3000/admin/queues
# Scraper at http://localhost:8090
```

| Service              | Port            | Role                                              |
| -------------------- | --------------- | ------------------------------------------------- |
| `scraper-standalone` | 8090            | HTTP scraping engine (IG + TikTok)                |
| `pipeline`           | 3000            | BullMQ workers + scheduler (enrich-creator, etc.) |
| `redis`              | 6379 (internal) | BullMQ queue broker                               |

**Local dev (without Docker):**

```bash
# Terminal 1: Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine \
  redis-server --requirepass changeme

# Terminal 2: Pipeline
cd pipeline && bun --watch src/index.ts

# Terminal 3: Scraper
cd scraper-standalone && npm run dev
```

### 4. Bull Board Dashboard

Access the queue monitoring dashboard at **http://localhost:3000/admin/queues**.

If `BULL_BOARD_PASSWORD` is set, authenticate with username `admin` and your chosen password.

The dashboard shows:

- All 9 queues with job counts (waiting, active, completed, failed)
- Individual job details, data, and error logs
- Repeatable job schedules (enrich-tick, batch-submit, batch-poll, synthesis)
- Ability to retry failed jobs or clean completed ones

### 5. Test it

**Health check:**

```bash
curl http://localhost:8090/health
```

```json
{
  "status": "ok",
  "service": "scraper-standalone",
  "uptime": 12.345,
  "proxyConfigured": true,
  "kernelConfigured": true
}
```

**Scrape an Instagram profile:**

```bash
curl -X POST http://localhost:8090/scrape/instagram \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_worker_api_key" \
  -d '{"username": "natgeo", "maxPosts": 50, "includeReels": true}'
```

```json
{
  "username": "natgeo",
  "status": "success",
  "profile": {
    "id": "787132",
    "username": "natgeo",
    "fullName": "National Geographic",
    "biography": "Experience the world through the eyes of...",
    "externalUrl": "https://natgeo.com",
    "profilePicUrl": "https://scontent-...",
    "profilePicUrlHd": "https://scontent-...",
    "isVerified": true,
    "isPrivate": false,
    "isBusinessAccount": true,
    "isProfessionalAccount": true,
    "businessCategory": "Media/News Company",
    "followerCount": 283000000,
    "followingCount": 150,
    "postCount": 28500,
    "highlightReelCount": 12,
    "pronouns": []
  },
  "posts": [
    {
      "id": "3456789012345678901",
      "shortcode": "CxYz123",
      "type": "reel",
      "caption": "A rare snow leopard spotted in the wild 🐆 #nature",
      "displayUrl": "https://scontent-...",
      "videoUrl": "https://scontent-...",
      "thumbnailUrl": "https://scontent-...",
      "likeCount": 245000,
      "commentCount": 1200,
      "viewCount": 5800000,
      "timestamp": "2026-02-10T14:30:00.000Z",
      "location": { "id": "123456", "name": "Himalayas" },
      "taggedUsers": ["photographer_name"],
      "hashtags": ["nature"],
      "mentions": [],
      "carouselMedia": null,
      "musicInfo": { "songName": "Original Audio", "artistName": "natgeo" }
    }
  ],
  "reels": [{ "...": "same structure as posts, filtered to type=reel" }],
  "scraped_at": "2026-02-14T23:45:00.000Z"
}
```

**Scrape a TikTok profile:**

```bash
curl -X POST http://localhost:8090/scrape/tiktok \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_worker_api_key" \
  -d '{"username": "charlidamelio"}'
```

```json
{
  "username": "charlidamelio",
  "status": "success",
  "profile": {
    "id": "5831967",
    "username": "charlidamelio",
    "displayName": "Charli D'Amelio",
    "bio": "don't worry about it",
    "avatarUrl": "https://p16-...",
    "isVerified": true,
    "followerCount": 155000000,
    "followingCount": 1200,
    "likeCount": 12000000000,
    "videoCount": 2400
  },
  "videos": [
    {
      "id": "7123456789012345678",
      "description": "new dance 💃 #fyp",
      "createTime": "2026-02-10T14:30:00.000Z",
      "coverUrl": "https://p16-...",
      "videoUrl": "https://v16-...",
      "duration": 15,
      "playCount": 45000000,
      "likeCount": 3200000,
      "commentCount": 42000,
      "shareCount": 120000,
      "collectCount": 85000,
      "hashtags": ["fyp"]
    }
  ],
  "scraped_at": "2026-02-14T23:45:00.000Z"
}
```

**Error responses:**

```json
// 401 — Missing or wrong API key
{ "error": "Unauthorized" }

// 400 — Bad request
{ "error": "\"username\" (string) is required" }

// 500 — Scraping error (rate limit, block, etc.)
{ "error": "Rate limited by Instagram (429)" }
```

### 6. Refresh Instagram doc_ids

Instagram's GraphQL `doc_id` values expire every 2-4 weeks. When pagination stops working (returning only 12 posts):

**Quick check:** Look at the scraper logs for `GraphQL posts returned unexpected format` or `execution error`. This means the doc_id or request format has changed.

**How to find new doc_ids:**

1. Open Instagram in Chrome → DevTools (F12) → Network → filter `graphql`
2. Visit a profile and scroll to trigger pagination
3. Inspect the request payload for `doc_id=` and the response structure
4. Update `src/instagram/config.ts` with the new values

Alternatively, check [ScrapFly's open-source scraper](https://github.com/scrapfly/scrapfly-scrapers/blob/main/instagram-scraper/instagram.py) — they update doc_ids within hours of Instagram changes.

```bash
# Playwright discovery script (intercepts both GET and POST GraphQL)
cd scraper-standalone
npm install -D playwright
npm run discover           # default profile
npm run discover -- natgeo # specific profile
```

**Reels doc_id discovery** requires a logged-in session (Instagram blocks Reels tab GraphQL for anonymous users). To run authenticated:

1. Run locally with `headless: false` → log in manually when browser opens
2. Save session: `context.storageState({ path: 'auth.json' })`
3. Copy `auth.json` to VM for headless runs: `browser.newContext({ storageState: 'auth.json' })`
4. Sessions last ~2-4 weeks before cookies expire

**Fallback behavior:** When the reels doc_id is stale, `fetchReels()` automatically falls back to the posts doc_id and filters to `product_type='clips'`. This gets reels posted to the grid but misses reels-only posts.

> **Note:** As of Feb 2026, Instagram uses the XDT GraphQL format for posts and reels. The response is at `data.xdt_api__v1__feed__user_timeline_graphql_connection` and variables require `username` + relay internal flags. If only the doc_id changes but the format stays the same, just update `config.ts`. If the response structure also changes, update `posts.ts`.

## Scraper Architecture

### Instagram scraping flow

```
POST /scrape/instagram { username: "natgeo", maxPosts: 50 }
  │
  ├─ InstagramClient.get() ─► i.instagram.com REST API
  │    └─ impit (TLS fingerprint) + Apify proxy (datacenter → residential)
  │    └─ Returns profile + first ~12 posts
  │
  ├─ InstagramClient.initSession() ─► instagram.com/
  │    └─ Acquires csrftoken cookie for GraphQL auth
  │
  ├─ [if maxPosts > 12] fetchAllPosts() ─► instagram.com/graphql/query (GET)
  │    └─ XDT format: username-based variables + relay internal flags
  │    └─ Response: data.xdt_api__v1__feed__user_timeline_graphql_connection
  │    └─ 12 posts per page, human-like delays (2-5s), cursor pagination
  │    └─ Reels with product_type='clips' are extracted from timeline
  │
  └─ Returns ProfileResult { username, status, profile, posts, reels, scraped_at }
```

### TikTok scraping flow

```
POST /scrape/tiktok { username: "charlidamelio" }
  │
  ├─ TikTokClient.getProfileHtml() ─► tiktok.com/@username
  │    └─ impit + Apify residential proxy
  │    └─ Extracts __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON
  │
  ├─ [if include_videos] fetchVideos() ─► OnKernel cloud browser
  │    └─ Playwright script intercepts /api/post/item_list/ API calls
  │    └─ Scrolls for pagination
  │
  └─ Returns TikTokProfileResult { username, status, profile, videos, scraped_at }
```

### Proxy strategy

| Platform  | Initial proxy | On 403 block            | Cooldown                      |
| --------- | ------------- | ----------------------- | ----------------------------- |
| Instagram | Datacenter    | Escalate to residential | 15-min cooldown after 3 fails |
| TikTok    | Residential   | Rotate session          | —                             |

### Rate limiting

Instagram requests use a token-bucket rate limiter (150 req/hr) to stay under Instagram's ~200/hr limit. Requests that exceed the budget are delayed automatically.

## Deployment Roadmap

Scraping and AI are **fully decoupled** — get scraping working first, add AI later.

### Phase 1: Scraping (current focus)

Get `scraper-standalone` running on the GCP VM. This only needs:

- **Apify proxy** — for IG + TikTok HTTP requests
- **OnKernel** (optional) — for TikTok video scraping via cloud browsers

No database, no AI, no embeddings required. The scraper returns JSON over HTTP — test it directly with `curl`.

### Phase 2: Storage + Pipeline

Add `pipeline` + `redis` to the VM via Docker Compose. Connect to:

- **PostgreSQL** (PlanetScale) — persist scraped profiles + posts
- **GCS** — download and store media (videos, thumbnails, profile pics)

### Phase 3: AI Analysis + Embeddings

Enable the analysis workers. Requires:

- **Google Gemini** — video analysis (batch API, 50% cheaper) + creator synthesis
- **Vercel AI Gateway** — embedding generation
- **Qdrant** — vector storage + semantic search

> **Gemini does NOT scrape.** It only analyzes videos and synthesizes creator profiles AFTER scraping and media download are complete.

## GitHub Secrets

Set in **Settings → Secrets → Actions** for CI/CD to work:

| Secret                 | Used by       | Purpose                            |
| ---------------------- | ------------- | ---------------------------------- |
| `APIFY_PROXY_PASSWORD` | Docker deploy | Passed to scraper-standalone       |
| `WORKER_API_KEY`       | Docker deploy | Auth between pipeline ↔ scraper    |
| `KERNEL_API_KEY`       | Docker deploy | OnKernel cloud browsers for TikTok |

## 3rd Party Services

| Service              | Status                      | Used for                                   | Phase |
| :------------------- | :-------------------------- | :----------------------------------------- | :---- |
| Apify Proxy          | 🔄 Migrating to StatProxies | Residential + datacenter proxies for IG/TT | 1     |
| OnKernel             | ⬜ Not yet configured       | Cloud browsers for TikTok video scraping   | 1     |
| PlanetScale Metal    | ✅ Active                   | PostgreSQL — profiles, posts, analyses     | 2     |
| Google Cloud Storage | 🔄 Migrating from R2        | Object storage — videos, thumbnails, JSON  | 2     |
| Qdrant Cloud         | ✅ Active                   | Vector search — 22 collections, 3072 dims  | 3     |
| Google Gemini        | ✅ Active                   | Video analysis (batch 50% off) + synthesis | 3     |
| Vercel AI Gateway    | ✅ Active                   | Embeddings only                            | 3     |
| ScrapeCreators       | ✅ Active                   | TikTok + on-demand IG fallback             | 1     |
| Apify API            | ✅ Active                   | IG fallback when ScrapeCreators fails      | 1     |

## Migration from trendsweep-b2b

This pipeline is being extracted from the `trendsweep-b2b` monorepo. Both repos share the same database and Qdrant cluster.

```
trendsweep-b2b (Next.js)          atlas-pipeline (this repo)
─────────────────────────         ──────────────────────────
Admin UI → HTTP calls ──────────► scraper-standalone / pipeline workers
Server actions → reads DB ◄──────► Same PlanetScale DB
/explore → reads Qdrant  ◄──────► Same Qdrant cluster
```

### Frontend → VM Integration (live)

The `trendsweep-b2b` app's scrape routes (`/api/admin/scrape/*` and `/api/v1/scrape/*`) **try the VM first** at `http://34.66.222.44:8090` via `SCRAPER_URL` + `SCRAPER_API_KEY` bearer auth. If the VM fails or `SCRAPER_URL` is not set, routes **fall back to legacy local scraping** so prod stays up.

**Vercel env vars:**

| Variable          | Value                                              |
| ----------------- | -------------------------------------------------- |
| `SCRAPER_URL`     | `http://34.66.222.44:8090`                         |
| `SCRAPER_API_KEY` | Bearer token (same value as VM's `WORKER_API_KEY`) |

> `APIFY_PROXY_PASSWORD` and `KERNEL_API_KEY` are no longer needed on Vercel — the VM handles those.

**HTTPS upgrade (future):** If needed, point a subdomain (e.g. `scraper.trendsweep.com`) at `34.66.222.44` and add nginx. Currently not needed since Vercel proxies server-side. See `DEPLOYMENT.md`.
