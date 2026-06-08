import os
import time
from typing import List
from openai import OpenAI
from pydantic import BaseModel, Field

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_MODEL = "gemini-3.1-flash-lite"
_RATE_LIMIT_SLEEP = 4  # 60s ÷ 15 RPM free tier

_CURATOR_PROMPT = """You are an expert AI news curator specializing in personalized content ranking for AI professionals.

Your role is to analyze and rank AI-related news articles, research papers, and video content based on a user's specific profile, interests, and background.

Ranking Criteria:
1. Relevance to user's stated interests and background
2. Technical depth and practical value
3. Novelty and significance of the content
4. Alignment with user's expertise level
5. Actionability and real-world applicability

Scoring Guidelines:
- 9.0-10.0: Highly relevant, directly aligns with user interests, significant value
- 7.0-8.9: Very relevant, strong alignment with interests, good value
- 5.0-6.9: Moderately relevant, some alignment, decent value
- 3.0-4.9: Somewhat relevant, limited alignment, lower value
- 0.0-2.9: Low relevance, minimal alignment, little value

Rank articles from most relevant (rank 1) to least relevant. Ensure each article has a unique rank."""


class RankedArticle(BaseModel):
    digest_id: str = Field(description="The ID of the digest (article_type:article_id)")
    relevance_score: float = Field(description="Relevance score from 0.0 to 10.0", ge=0.0, le=10.0)
    rank: int = Field(description="Rank position (1 = most relevant)", ge=1)
    reasoning: str = Field(description="Brief explanation of why this article is ranked here")


class RankedDigestList(BaseModel):
    articles: List[RankedArticle] = Field(description="List of ranked articles")


class CuratorAgent:
    def __init__(self, user_profile: dict):
        self.client = OpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url=_GEMINI_URL)
        self.model = _MODEL
        self.user_profile = user_profile
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        interests = "\n".join(f"- {i}" for i in self.user_profile["interests"])
        pref_text = "\n".join(f"- {k}: {v}" for k, v in self.user_profile["preferences"].items())
        return f"""{_CURATOR_PROMPT}

User Profile:
Name: {self.user_profile["name"]}
Background: {self.user_profile["background"]}
Expertise Level: {self.user_profile["expertise_level"]}

Interests:
{interests}

Preferences:
{pref_text}"""

    def rank_digests(self, digests: List[dict]) -> List[RankedArticle]:
        if not digests:
            return []

        digest_list = "\n\n".join(
            f"ID: {d['id']}\nTitle: {d['title']}\nSummary: {d['summary']}\nType: {d['article_type']}"
            for d in digests
        )
        user_prompt = (
            f"Rank these {len(digests)} AI news digests based on the user profile:\n\n{digest_list}\n\n"
            f"Provide a relevance score (0.0-10.0) and rank (1-{len(digests)}) for each article, ordered from most to least relevant."
            '\n\nReturn a JSON object with exactly: {"articles": [{"digest_id": "...", '
            '"relevance_score": 0.0, "rank": 1, "reasoning": "..."}]}'
        )

        try:
            time.sleep(_RATE_LIMIT_SLEEP)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            ranked_list = RankedDigestList.model_validate_json(response.choices[0].message.content)
            return ranked_list.articles if ranked_list else []
        except Exception as e:
            print(f"Error ranking digests: {e}")
            return []
