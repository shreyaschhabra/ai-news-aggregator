import logging
from typing import Optional

from app.scrapers.anthropic import AnthropicScraper
from app.scrapers.youtube import YouTubeScraper
from app.agent.digest_agent import DigestAgent
from app.database.repository import Repository

logger = logging.getLogger(__name__)

_TRANSCRIPT_UNAVAILABLE = "__UNAVAILABLE__"


def process_anthropic_markdown() -> dict:
    scraper = AnthropicScraper()
    repo = Repository()
    articles = repo.get_anthropic_articles_without_markdown()
    processed = failed = 0
    for article in articles:
        markdown = scraper.url_to_markdown(article.url)
        if markdown:
            repo.update_anthropic_article_markdown(article.guid, markdown)
            processed += 1
        else:
            failed += 1
    return {"total": len(articles), "processed": processed, "failed": failed}


def process_youtube_transcripts(limit: Optional[int] = None) -> dict:
    scraper = YouTubeScraper()
    repo = Repository()
    videos = repo.get_youtube_videos_without_transcript(limit=limit)
    processed = unavailable = 0
    for video in videos:
        transcript = scraper.get_transcript(video.video_id)
        if transcript:
            repo.update_youtube_video_transcript(video.video_id, transcript)
            processed += 1
        else:
            repo.update_youtube_video_transcript(video.video_id, _TRANSCRIPT_UNAVAILABLE)
            unavailable += 1
    return {"total": len(videos), "processed": processed, "unavailable": unavailable}


def process_digests(limit: Optional[int] = None) -> dict:
    agent = DigestAgent()
    repo = Repository()
    articles = repo.get_articles_without_digest(limit=limit)
    total = len(articles)
    processed = failed = 0

    logger.info(f"Processing {total} articles for digest")
    for idx, article in enumerate(articles, 1):
        label = article["title"][:60] + "..." if len(article["title"]) > 60 else article["title"]
        logger.info(f"[{idx}/{total}] {article['type']}: {label}")
        try:
            result = agent.generate_digest(
                title=article["title"], content=article["content"], article_type=article["type"]
            )
            if result:
                repo.create_digest(
                    article_type=article["type"], article_id=article["id"],
                    url=article["url"], title=result.title, summary=result.summary,
                    published_at=article.get("published_at"),
                )
                processed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error(f"Error on {article['type']} {article['id']}: {e}")

    logger.info(f"Digest complete: {processed} processed, {failed} failed / {total}")
    return {"total": total, "processed": processed, "failed": failed}
