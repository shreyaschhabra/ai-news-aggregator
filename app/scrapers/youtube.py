from datetime import datetime, timedelta, timezone
from typing import List, Optional
import os
import feedparser
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.proxies import WebshareProxyConfig


class ChannelVideo(BaseModel):
    title: str
    url: str
    video_id: str
    published_at: datetime
    description: str
    transcript: Optional[str] = None


class YouTubeScraper:
    def __init__(self):
        proxy_username = os.getenv("PROXY_USERNAME")
        proxy_password = os.getenv("PROXY_PASSWORD")
        proxy_config = WebshareProxyConfig(proxy_username=proxy_username, proxy_password=proxy_password) if proxy_username and proxy_password else None
        self.transcript_api = YouTubeTranscriptApi(proxy_config=proxy_config)

    def _get_rss_url(self, channel_id: str) -> str:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    def _extract_video_id(self, video_url: str) -> str:
        if "youtube.com/watch?v=" in video_url:
            return video_url.split("v=")[1].split("&")[0]
        if "youtube.com/shorts/" in video_url:
            return video_url.split("shorts/")[1].split("?")[0]
        if "youtu.be/" in video_url:
            return video_url.split("youtu.be/")[1].split("?")[0]
        return video_url

    def get_transcript(self, video_id: str) -> Optional[str]:
        try:
            transcript = self.transcript_api.fetch(video_id)
            return " ".join([snippet.text for snippet in transcript.snippets])
        except Exception:
            return None

    def get_latest_videos(self, channel_id: str, hours: int = 24) -> List[ChannelVideo]:
        feed = feedparser.parse(self._get_rss_url(channel_id))
        if not feed.entries:
            return []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        videos = []
        for entry in feed.entries:
            if "/shorts/" in entry.link:
                continue
            published_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published_time >= cutoff_time:
                videos.append(ChannelVideo(
                    title=entry.title,
                    url=entry.link,
                    video_id=self._extract_video_id(entry.link),
                    published_at=published_time,
                    description=entry.get("summary", "")
                ))
        return videos
