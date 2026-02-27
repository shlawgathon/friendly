"""Async pipeline orchestrator — coordinates the ingestion job."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from app.config import settings
from app.services import scraper, reka, pioneer, yutori, graph, modulate

logger = logging.getLogger(__name__)


async def run_instagram_ingest(job_id: str, username: str, user_id: str,
                               max_posts: int = 10, include_reels: bool = True) -> None:
    """Full Instagram ingestion pipeline. Runs as background task."""
    failed_steps: list[str] = []

    try:
        await graph.update_ingest_job(job_id, "processing", progress={"step": "scraping"})

        # ── Step 1: Scrape Instagram ──
        try:
            scrape_data = await scraper.scrape_instagram(username, max_posts, include_reels)
        except Exception as e:
            logger.error("Scraper failed for @%s: %s", username, e)
            await graph.update_ingest_job(job_id, "failed", error=f"Scraper error: {e}")
            return

        profile = scrape_data.get("profile", {})

        # Create user node
        await graph.create_user(
            user_id=user_id,
            username=username,
            full_name=profile.get("fullName"),
            bio=profile.get("biography"),
            profile_pic_url=profile.get("profilePicUrl"),
        )

        await graph.update_ingest_job(job_id, "processing", progress={"step": "analyzing_media"})

        # ── Step 2: Reka — analyze images ──
        posts = scrape_data.get("posts", [])
        captions: list[str] = []

        # Bio text is always useful
        bio_text = profile.get("biography", "")
        if bio_text:
            captions.append(bio_text)

        # Add post captions
        for post in posts:
            if post.get("caption"):
                captions.append(post["caption"])

        # Analyze images with Reka (semaphore-gated)
        # Collect all image URLs paired with their post caption for context
        image_items: list[tuple[str, str]] = []  # (url, caption)
        for p in posts:
            cap = p.get("caption", "")
            if p.get("slideUrls"):  # Carousel: use all slide images
                for url in p["slideUrls"]:
                    image_items.append((url, cap))
            elif p.get("displayUrl"):  # Single image
                image_items.append((p["displayUrl"], cap))

        reka_tasks = []
        for url, cap in image_items[:max_posts * 3]:  # allow more images for carousels
            reka_tasks.append(_safe_reka_analyze(url, failed_steps, caption=cap))

        if reka_tasks:
            reka_results = await asyncio.gather(*reka_tasks)
            captions.extend([r for r in reka_results if r])

        await graph.update_ingest_job(job_id, "processing", progress={"step": "extracting_entities"})

        # ── Step 3: Extract interests from all text ──
        combined_text = "\n\n".join(captions)

        # Primary: use Reka to extract structured interests
        extraction = await reka.extract_interests(combined_text)
        entities = extraction.get("entities", {})

        # Fallback: try Pioneer if Reka returned nothing
        if not entities:
            try:
                extraction = await pioneer.extract_entities(combined_text)
                entities = extraction.get("entities", {})
            except Exception as e:
                logger.warning("Pioneer fallback also failed: %s", e)

        # Write entities to graph
        entity_count = await graph.add_entities_from_extraction(user_id, entities, source="visual")
        logger.info("Added %d entities for @%s", entity_count, username)

        await graph.update_ingest_job(job_id, "processing", progress={"step": "submitting_research"})

        # ── Step 4: Yutori — submit research + scouting for top interests ──
        interests = await graph.get_user_interests(user_id)
        top_interests = interests[:settings.top_interests_for_yutori]
        webhook_url = f"{settings.webhook_base_url}/api/webhooks/yutori"

        for interest_rec in top_interests:
            interest_name = interest_rec["hobby"]
            try:
                # Research task
                research_result = await yutori.submit_research_task(interest_name, webhook_url=webhook_url)
                if research_result.get("task_id"):
                    await graph.create_task_record(
                        provider_task_id=research_result["task_id"],
                        task_type="research",
                        interest=interest_name,
                        user_id=user_id,
                    )

                # Scouting task
                scouting_result = await yutori.submit_scouting_task(interest_name, webhook_url=webhook_url)
                if scouting_result.get("id"):
                    await graph.create_task_record(
                        provider_task_id=scouting_result["id"],
                        task_type="scouting",
                        interest=interest_name,
                        user_id=user_id,
                    )
            except Exception as e:
                logger.warning("Yutori submit failed for '%s': %s", interest_name, e)
                failed_steps.append(f"yutori:{interest_name}")

        # ── Done ──
        await graph.update_ingest_job(
            job_id, "completed",
            result={"entities_added": entity_count, "posts_analyzed": len(posts), "failed_steps": failed_steps},
        )
        logger.info("Instagram ingest complete for @%s (job %s)", username, job_id)

    except Exception as e:
        logger.exception("Pipeline error for job %s", job_id)
        await graph.update_ingest_job(job_id, "failed", error=str(e))


async def _safe_reka_analyze(url: str, failed_steps: list[str], caption: str = "") -> str | None:
    """Analyze a single image, returning None on failure (partial success)."""
    try:
        return await reka.analyze_image(url, caption=caption)
    except Exception as e:
        logger.warning("Reka failed for %s: %s", url[:60], e)
        failed_steps.append(f"reka:{url[:60]}")
        return None


async def run_voice_ingest(job_id: str, user_id: str, audio_data: bytes, filename: str) -> None:
    """Voice ingestion pipeline."""
    try:
        await graph.update_ingest_job(job_id, "processing", progress={"step": "transcribing"})

        # Step 1: Modulate STT
        transcript = await modulate.transcribe_audio(audio_data, filename)
        text = transcript.get("text", "")

        if not text:
            await graph.update_ingest_job(job_id, "failed", error="No transcript returned")
            return

        await graph.update_ingest_job(job_id, "processing", progress={"step": "extracting_entities"})

        # Step 2: Pioneer NER
        extraction = await pioneer.extract_entities(text)
        entities = extraction.get("entities", {})

        # Step 3: Write to graph
        entity_count = await graph.add_entities_from_extraction(user_id, entities, source="voice")

        # Emotion context from Modulate
        utterances = transcript.get("utterances", [])
        emotions = [u.get("emotion") for u in utterances if u.get("emotion") and u["emotion"] != "Neutral"]
        if emotions:
            logger.info("Voice emotions detected: %s", emotions)

        await graph.update_ingest_job(
            job_id, "completed",
            result={"entities_added": entity_count, "transcript_length": len(text), "emotions": emotions},
        )

    except Exception as e:
        logger.exception("Voice pipeline error for job %s", job_id)
        await graph.update_ingest_job(job_id, "failed", error=str(e))
