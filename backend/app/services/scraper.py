"""Instagram scraper — uses Instaloader Python API (no proxy needed)."""
from __future__ import annotations

import asyncio
import logging
from itertools import islice

import instaloader
from instaloader import Profile

from app.config import settings

logger = logging.getLogger(__name__)

# Reuse a single Instaloader instance
_loader: instaloader.Instaloader | None = None


def _get_loader() -> instaloader.Instaloader:
    global _loader
    if _loader is None:
        _loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )
    return _loader


def _scrape_sync(username: str, max_posts: int, include_reels: bool) -> dict:
    """Synchronous scraping via Instaloader. Runs in a thread."""
    loader = _get_loader()
    profile = Profile.from_username(loader.context, username)

    # Profile data
    profile_data = {
        "username": profile.username,
        "fullName": profile.full_name,
        "biography": profile.biography,
        "followers": profile.followers,
        "followees": profile.followees,
        "profilePicUrl": profile.profile_pic_url,
        "externalUrl": profile.external_url,
        "isPrivate": profile.is_private,
    }

    posts = []
    reels = []

    if not profile.is_private:
        for post in islice(profile.get_posts(), max_posts):
            post_data = {
                "shortcode": post.shortcode,
                "caption": post.caption or "",
                "displayUrl": post.url,
                "timestamp": post.date_utc.isoformat(),
                "likes": post.likes,
                "isVideo": post.is_video,
                "typename": post.typename,
            }

            # For carousels, collect all slide image URLs
            if post.typename == "GraphSidecar":
                slide_urls = []
                try:
                    for node in post.get_sidecar_nodes():
                        if not node.is_video:
                            slide_urls.append(node.display_url)
                except Exception:
                    pass  # Fall back to single displayUrl
                if slide_urls:
                    post_data["slideUrls"] = slide_urls
                posts.append(post_data)
            elif post.is_video and post.typename == "GraphVideo":
                # Separate reels from regular posts
                if include_reels:
                    post_data["videoUrl"] = post.video_url
                    reels.append(post_data)
                else:
                    posts.append(post_data)
            else:
                posts.append(post_data)

    return {
        "profile": profile_data,
        "posts": posts,
        "reels": reels,
    }


async def scrape_instagram(username: str, max_posts: int = 10, include_reels: bool = True) -> dict:
    """Scrape Instagram profile and posts using Instaloader.

    Runs the blocking Instaloader calls in a thread to avoid blocking the event loop.
    """
    capped_max = min(max_posts, settings.max_posts_hard_limit)

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_scrape_sync, username, capped_max, include_reels),
            timeout=60.0,  # generous timeout for scraping
        )
        logger.info(
            "Scraped @%s: %d posts, %d reels, private=%s",
            username, len(data["posts"]), len(data["reels"]), data["profile"]["isPrivate"],
        )
        return data
    except asyncio.TimeoutError:
        logger.error("Instaloader timeout for @%s", username)
        raise
    except instaloader.exceptions.ProfileNotExistsException:
        logger.warning("Profile @%s does not exist", username)
        raise ValueError(f"Instagram profile '@{username}' not found")
    except instaloader.exceptions.PrivateProfileNotFollowedException:
        logger.warning("Profile @%s is private", username)
        # Return profile data without posts
        loader = _get_loader()
        profile = Profile.from_username(loader.context, username)
        return {
            "profile": {
                "username": profile.username,
                "fullName": profile.full_name,
                "biography": profile.biography,
                "profilePicUrl": profile.profile_pic_url,
                "isPrivate": True,
            },
            "posts": [],
            "reels": [],
        }
    except Exception as e:
        logger.error("Instaloader error for @%s: %s", username, e)
        raise
