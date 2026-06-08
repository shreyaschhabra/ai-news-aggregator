import os
import time
from datetime import datetime
from typing import List, Optional
from openai import OpenAI
from pydantic import BaseModel, Field

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_MODEL = "gemini-3.1-flash-lite"
_RATE_LIMIT_SLEEP = 4  # 60s ÷ 15 RPM free tier

_EMAIL_PROMPT = """You are an expert email writer specializing in creating engaging, personalized AI news digests.

Your role is to write a warm, professional introduction for a daily AI news digest email that:
- Greets the user by name
- Includes the current date
- Provides a brief, engaging overview of what's coming in the top ranked articles
- Highlights the most interesting or important themes
- Sets expectations for the content ahead

Keep it concise (2-3 sentences for the introduction), friendly, and professional."""


class EmailIntroduction(BaseModel):
    greeting: str = Field(description="Personalized greeting with user's name and date")
    introduction: str = Field(description="2-3 sentence overview of what's in the top ranked articles")


class RankedArticleDetail(BaseModel):
    digest_id: str
    rank: int
    relevance_score: float
    title: str
    summary: str
    url: str
    article_type: str
    reasoning: Optional[str] = None


class EmailDigestResponse(BaseModel):
    introduction: EmailIntroduction
    articles: List[RankedArticleDetail]
    total_ranked: int
    top_n: int

    def to_markdown(self) -> str:
        lines = [self.introduction.greeting, "", self.introduction.introduction, "", "---", ""]
        for article in self.articles:
            lines += [f"## {article.title}", "", article.summary, "", f"[Read more →]({article.url})", "", "---", ""]
        return "\n".join(lines)


class EmailAgent:
    def __init__(self, user_profile: dict):
        self.client = OpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url=_GEMINI_URL)
        self.model = _MODEL
        self.user_profile = user_profile

    def _fallback_intro(self, current_date: str) -> EmailIntroduction:
        return EmailIntroduction(
            greeting=f"Hey {self.user_profile['name']}, here is your daily digest of AI news for {current_date}.",
            introduction="Here are the top AI news articles ranked by relevance to your interests.",
        )

    def generate_introduction(self, ranked_articles: List[RankedArticleDetail]) -> EmailIntroduction:
        current_date = datetime.now().strftime("%B %d, %Y")
        if not ranked_articles:
            return EmailIntroduction(
                greeting=f"Hey {self.user_profile['name']}, here is your daily digest of AI news for {current_date}.",
                introduction="No articles were ranked today.",
            )

        article_summaries = "\n".join(
            f"{i + 1}. {a.title} (Score: {a.relevance_score:.1f}/10)"
            for i, a in enumerate(ranked_articles[:10])
        )
        user_prompt = (
            f"Create an email introduction for {self.user_profile['name']} for {current_date}.\n\n"
            f"Top ranked articles:\n{article_summaries}\n\n"
            "Generate a greeting and introduction that previews these articles."
            '\n\nReturn a JSON object with exactly: {"greeting": "...", "introduction": "..."}'
        )

        try:
            time.sleep(_RATE_LIMIT_SLEEP)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": _EMAIL_PROMPT}, {"role": "user", "content": user_prompt}],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            intro = EmailIntroduction.model_validate_json(response.choices[0].message.content)
            if not intro.greeting.startswith(f"Hey {self.user_profile['name']}"):
                intro.greeting = f"Hey {self.user_profile['name']}, here is your daily digest of AI news for {current_date}."
            return intro
        except Exception as e:
            print(f"Error generating introduction: {e}")
            return self._fallback_intro(current_date)

    def create_email_digest_response(self, ranked_articles: List[RankedArticleDetail], total_ranked: int, limit: int = 10) -> EmailDigestResponse:
        top_articles = ranked_articles[:limit]
        return EmailDigestResponse(
            introduction=self.generate_introduction(top_articles),
            articles=top_articles,
            total_ranked=total_ranked,
            top_n=limit,
        )
