import logging
from typing import Any

from app.db.neo4j import get_session
from app.models.enrichment import DeepInsight, VibeFingerprint

logger = logging.getLogger(__name__)


class GraphWriter:
    """Writes Tier 3 deep enrichment data to Neo4j."""

    async def write_deep_insights(
        self, username: str, insights: list[DeepInsight]
    ) -> None:
        """Create DeepInsight nodes and (:User)-[:HAS_INSIGHT]->(:DeepInsight) relationships."""
        if not insights:
            logger.info("No insights to write for %s", username)
            return

        async with get_session() as session:
            for insight in insights:
                await session.run(
                    """
                    MATCH (u:User {username: $username})
                    CREATE (di:DeepInsight {
                        type: $type,
                        content: $content,
                        source_url: $source_url,
                        interests_found: $interests_found,
                        source: 'n1',
                        tier: 3
                    })
                    CREATE (u)-[:HAS_INSIGHT]->(di)
                    """,
                    username=username,
                    type=insight.type,
                    content=insight.content,
                    source_url=insight.source_url,
                    interests_found=insight.interests_found,
                )

            logger.info(
                "Wrote %d DeepInsight nodes for %s", len(insights), username
            )

    async def write_vibe_profile(
        self, username: str, vibe: VibeFingerprint
    ) -> None:
        """MERGE a VibeProfile node and create (:User)-[:HAS_VIBE]->(:VibeProfile)."""
        async with get_session() as session:
            await session.run(
                """
                MATCH (u:User {username: $username})
                MERGE (v:VibeProfile {username: $username})
                SET v.aesthetic_tags = $aesthetic_tags,
                    v.color_palette = $color_palette,
                    v.mood = $mood,
                    v.energy = $energy,
                    v.content_themes = $content_themes,
                    v.source = 'n1'
                MERGE (u)-[:HAS_VIBE]->(v)
                """,
                username=username,
                aesthetic_tags=vibe.aesthetic_tags,
                color_palette=vibe.color_palette,
                mood=vibe.mood,
                energy=vibe.energy,
                content_themes=vibe.content_themes,
            )

            logger.info("Wrote VibeProfile for %s", username)

    async def write_similar_vibe(
        self,
        username_a: str,
        username_b: str,
        score: float,
        shared_aesthetics: list[str],
        shared_themes: list[str],
    ) -> None:
        """Create bidirectional SIMILAR_VIBE relationships between VibeProfiles.

        Only writes if score > 0.3.
        """
        if score <= 0.3:
            logger.info(
                "Vibe similarity %.3f between %s and %s below threshold 0.3, skipping",
                score,
                username_a,
                username_b,
            )
            return

        async with get_session() as session:
            # Create bidirectional relationships
            await session.run(
                """
                MATCH (va:VibeProfile {username: $username_a})
                MATCH (vb:VibeProfile {username: $username_b})
                MERGE (va)-[r1:SIMILAR_VIBE]->(vb)
                SET r1.score = $score,
                    r1.shared_aesthetics = $shared_aesthetics,
                    r1.shared_themes = $shared_themes
                MERGE (vb)-[r2:SIMILAR_VIBE]->(va)
                SET r2.score = $score,
                    r2.shared_aesthetics = $shared_aesthetics,
                    r2.shared_themes = $shared_themes
                """,
                username_a=username_a,
                username_b=username_b,
                score=score,
                shared_aesthetics=shared_aesthetics,
                shared_themes=shared_themes,
            )

            logger.info(
                "Wrote SIMILAR_VIBE between %s and %s (score=%.3f)",
                username_a,
                username_b,
                score,
            )

    async def write_discovered_interests(
        self, username: str, interests: list[str]
    ) -> None:
        """MERGE Hobby nodes and create (:User)-[:INTERESTED_IN]->(:Hobby)
        for newly discovered interests from deep analysis."""
        if not interests:
            logger.info("No discovered interests to write for %s", username)
            return

        async with get_session() as session:
            for interest in interests:
                interest_clean = interest.strip().lower()
                if not interest_clean:
                    continue

                await session.run(
                    """
                    MATCH (u:User {username: $username})
                    MERGE (h:Hobby {name: $interest})
                    MERGE (u)-[r:INTERESTED_IN]->(h)
                    ON CREATE SET r.weight = 0.4,
                                  r.source = 'n1_deep',
                                  r.evidence = $evidence
                    """,
                    username=username,
                    interest=interest_clean,
                    evidence=f"Discovered via Tier 3 deep analysis of {username}'s profile",
                )

            logger.info(
                "Wrote %d discovered interests for %s", len(interests), username
            )

    async def get_vibe_profile(self, username: str) -> dict[str, Any] | None:
        """Read an existing VibeProfile for a user from Neo4j.

        Returns:
            A dict with the VibeProfile fields, or None if not found.
        """
        async with get_session() as session:
            result = await session.run(
                """
                MATCH (u:User {username: $username})-[:HAS_VIBE]->(v:VibeProfile)
                RETURN v.aesthetic_tags AS aesthetic_tags,
                       v.color_palette AS color_palette,
                       v.mood AS mood,
                       v.energy AS energy,
                       v.content_themes AS content_themes
                LIMIT 1
                """,
                username=username,
            )

            record = await result.single()

            if record is None:
                logger.info("No existing VibeProfile found for %s", username)
                return None

            vibe_data = {
                "aesthetic_tags": record["aesthetic_tags"] or [],
                "color_palette": record["color_palette"] or [],
                "mood": record["mood"] or "",
                "energy": record["energy"] if record["energy"] is not None else 0.5,
                "content_themes": record["content_themes"] or [],
            }

            logger.info("Found existing VibeProfile for %s", username)
            return vibe_data
