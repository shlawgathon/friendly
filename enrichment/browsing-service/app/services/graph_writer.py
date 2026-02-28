import logging
from typing import Any

from neo4j import AsyncSession

logger = logging.getLogger(__name__)


class GraphWriter:
    """Writes Tier 2 browsing enrichment results into the Neo4j graph."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _ensure_constraints(self) -> None:
        """Create uniqueness constraints if they do not already exist."""
        constraints = [
            "CREATE CONSTRAINT event_url IF NOT EXISTS FOR (e:Event) REQUIRE e.url IS UNIQUE",
            "CREATE CONSTRAINT community_url IF NOT EXISTS FOR (c:Community) REQUIRE c.url IS UNIQUE",
            "CREATE CONSTRAINT meetup_url IF NOT EXISTS FOR (m:Meetup) REQUIRE m.url IS UNIQUE",
        ]
        for stmt in constraints:
            await self._session.run(stmt)
        logger.debug("Neo4j constraints ensured")

    async def write_events(
        self,
        username: str,
        interest: str,
        events: list[dict[str, Any]],
    ) -> int:
        """Write Event nodes and connect them to User and Hobby nodes.

        Returns the number of events written.
        """
        if not events:
            return 0

        query = """
        UNWIND $events AS evt
        MERGE (e:Event {url: evt.url})
        SET e.title       = evt.title,
            e.date        = evt.date,
            e.location    = coalesce(evt.location, ''),
            e.description = coalesce(evt.description, ''),
            e.source      = 'browsing'

        WITH e, evt
        MERGE (h:Hobby {name: $interest})
        MERGE (h)-[:HAS_EVENT]->(e)

        WITH e
        MATCH (u:User {username: $username})
        MERGE (u)-[:ENRICHED_VIA {type: 'event', tier: 2}]->(e)
        """

        result = await self._session.run(
            query,
            events=events,
            interest=interest.lower(),
            username=username,
        )
        summary = await result.consume()
        count = summary.counters.nodes_created
        logger.info(
            "Wrote %d event node(s) for user=%s interest=%s",
            count,
            username,
            interest,
        )
        return count

    async def write_communities(
        self,
        username: str,
        interest: str,
        communities: list[dict[str, Any]],
    ) -> int:
        """Write Community nodes and connect them to User and Hobby nodes.

        Returns the number of communities written.
        """
        if not communities:
            return 0

        query = """
        UNWIND $communities AS comm
        MERGE (c:Community {url: comm.url})
        SET c.name             = comm.name,
            c.subscriber_count = coalesce(comm.subscriber_count, 0),
            c.description      = coalesce(comm.description, ''),
            c.source           = 'browsing'

        WITH c, comm
        MERGE (h:Hobby {name: $interest})
        MERGE (h)-[:HAS_COMMUNITY]->(c)

        WITH c
        MATCH (u:User {username: $username})
        MERGE (u)-[:ENRICHED_VIA {type: 'community', tier: 2}]->(c)
        """

        result = await self._session.run(
            query,
            communities=communities,
            interest=interest.lower(),
            username=username,
        )
        summary = await result.consume()
        count = summary.counters.nodes_created
        logger.info(
            "Wrote %d community node(s) for user=%s interest=%s",
            count,
            username,
            interest,
        )
        return count

    async def write_meetups(
        self,
        username: str,
        interest: str,
        meetups: list[dict[str, Any]],
    ) -> int:
        """Write Meetup nodes and connect them to User and Hobby nodes.

        Returns the number of meetups written.
        """
        if not meetups:
            return 0

        query = """
        UNWIND $meetups AS mt
        MERGE (m:Meetup {url: mt.url})
        SET m.name      = mt.name,
            m.date      = coalesce(mt.date, ''),
            m.location  = coalesce(mt.location, ''),
            m.attendees = coalesce(mt.attendees, 0),
            m.source    = 'browsing'

        WITH m, mt
        MERGE (h:Hobby {name: $interest})
        MERGE (h)-[:HAS_MEETUP]->(m)

        WITH m
        MATCH (u:User {username: $username})
        MERGE (u)-[:ENRICHED_VIA {type: 'meetup', tier: 2}]->(m)
        """

        result = await self._session.run(
            query,
            meetups=meetups,
            interest=interest.lower(),
            username=username,
        )
        summary = await result.consume()
        count = summary.counters.nodes_created
        logger.info(
            "Wrote %d meetup node(s) for user=%s interest=%s",
            count,
            username,
            interest,
        )
        return count

    async def write_browse_results(
        self,
        username: str,
        interest: str,
        events: list[dict[str, Any]],
        communities: list[dict[str, Any]],
        meetups: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Write all browsing enrichment results for a single interest.

        Returns a dict of counts: {"events": N, "communities": N, "meetups": N}.
        """
        await self._ensure_constraints()

        events_count = await self.write_events(username, interest, events)
        communities_count = await self.write_communities(
            username, interest, communities
        )
        meetups_count = await self.write_meetups(username, interest, meetups)

        return {
            "events": events_count,
            "communities": communities_count,
            "meetups": meetups_count,
        }
