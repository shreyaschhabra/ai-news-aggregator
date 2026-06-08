import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from app.config import YOUTUBE_CHANNELS
from app.scrapers.youtube import YouTubeScraper
from app.scrapers.openai import OpenAIScraper
from app.scrapers.anthropic import AnthropicScraper
from app.database.repository import Repository
from app.services.pipeline import process_anthropic_markdown, process_youtube_transcripts, process_digests
from app.services.email import send_digest_email
from app.stats_tracker import tracker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)


def _scrape_and_save(hours: int) -> dict:
    repo = Repository()
    youtube_videos = []
    video_dicts = []
    for channel_id in YOUTUBE_CHANNELS:
        videos = YouTubeScraper().get_latest_videos(channel_id, hours=hours)
        youtube_videos.extend(videos)
        video_dicts.extend([{
            "video_id": v.video_id, "title": v.title, "url": v.url,
            "channel_id": channel_id, "published_at": v.published_at,
            "description": v.description, "transcript": v.transcript,
        } for v in videos])

    openai_articles = OpenAIScraper().get_articles(hours=hours)
    anthropic_articles = AnthropicScraper().get_articles(hours=hours)

    if video_dicts:
        repo.bulk_create_youtube_videos(video_dicts)
    if openai_articles:
        repo.bulk_create_openai_articles([{
            "guid": a.guid, "title": a.title, "url": a.url,
            "published_at": a.published_at, "description": a.description, "category": a.category,
        } for a in openai_articles])
    if anthropic_articles:
        repo.bulk_create_anthropic_articles([{
            "guid": a.guid, "title": a.title, "url": a.url,
            "published_at": a.published_at, "description": a.description, "category": a.category,
        } for a in anthropic_articles])

    return {"youtube": youtube_videos, "openai": openai_articles, "anthropic": anthropic_articles}


def run_daily_pipeline(hours: int = 24, top_n: int = 10) -> dict:
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("Starting Daily AI News Aggregator Pipeline")
    logger.info("=" * 60)

    tracker.reset()
    results = {"start_time": start_time.isoformat(), "scraping": {}, "processing": {}, "digests": {}, "email": {}, "success": False}

    try:
        logger.info("\n[1/5] Scraping articles from sources...")
        scraped = _scrape_and_save(hours=hours)
        results["scraping"] = {k: len(v) for k, v in scraped.items()}
        logger.info(f"✓ YouTube: {results['scraping']['youtube']}, OpenAI: {results['scraping']['openai']}, Anthropic: {results['scraping']['anthropic']}")

        logger.info("\n[2/5] Processing Anthropic markdown...")
        anthropic_result = process_anthropic_markdown()
        results["processing"]["anthropic"] = anthropic_result
        logger.info(f"✓ {anthropic_result['processed']} processed, {anthropic_result['failed']} failed")

        logger.info("\n[3/5] Processing YouTube transcripts...")
        youtube_result = process_youtube_transcripts()
        results["processing"]["youtube"] = youtube_result
        logger.info(f"✓ {youtube_result['processed']} transcripts, {youtube_result['unavailable']} unavailable")

        logger.info("\n[4/5] Creating article digests...")
        digest_result = process_digests()
        results["digests"] = digest_result
        logger.info(f"✓ {digest_result['processed']}/{digest_result['total']} digests created")

        logger.info("\n[5/5] Generating and sending email digest...")
        email_result = send_digest_email(hours=hours, top_n=top_n)
        results["email"] = email_result
        if email_result["success"]:
            logger.info(f"✓ Email sent with {email_result['articles_count']} articles")
            results["success"] = True
        else:
            logger.error(f"✗ Email failed: {email_result.get('error')}")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        results["error"] = str(e)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    results.update({"end_time": end_time.isoformat(), "duration_seconds": duration})

    logger.info("\n" + "=" * 60)
    logger.info(f"Done in {duration:.1f}s | Email: {'Sent' if results['success'] else 'Failed'}")
    logger.info("=" * 60)

    tracker.print_summary()
    return results
