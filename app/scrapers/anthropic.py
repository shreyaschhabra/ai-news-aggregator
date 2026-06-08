from datetime import datetime, timedelta, timezone
from typing import List, Optional
import feedparser
from docling.document_converter import DocumentConverter
from pydantic import BaseModel


class AnthropicArticle(BaseModel):
    title: str
    description: str
    url: str
    guid: str
    published_at: datetime
    category: Optional[str] = None


class AnthropicScraper:
    RSS_URLS = [
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
    ]

    def __init__(self):
        self.converter = DocumentConverter()

    def get_articles(self, hours: int = 24) -> List[AnthropicArticle]:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        articles, seen_guids = [], set()
        for rss_url in self.RSS_URLS:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                published_parsed = getattr(entry, "published_parsed", None)
                if not published_parsed:
                    continue
                published_time = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                if published_time >= cutoff_time:
                    guid = entry.get("id", entry.get("link", ""))
                    if guid not in seen_guids:
                        seen_guids.add(guid)
                        articles.append(AnthropicArticle(
                            title=entry.get("title", ""),
                            description=entry.get("description", ""),
                            url=entry.get("link", ""),
                            guid=guid,
                            published_at=published_time,
                            category=entry.get("tags", [{}])[0].get("term") if entry.get("tags") else None
                        ))
        return articles

    def url_to_markdown(self, url: str) -> Optional[str]:
        try:
            return self.converter.convert(url).document.export_to_markdown()
        except Exception:
            return None
