import os
import time
from typing import Optional
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from app.stats_tracker import tracker

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_MODEL = "gemini-3.1-flash-lite"
_RATE_LIMIT_SLEEP = 4  # 60s ÷ 15 RPM free tier

_PROMPT = """You are an expert AI news analyst specializing in summarizing technical articles, research papers, and video content about artificial intelligence.

Your role is to create concise, informative digests that help readers quickly understand the key points and significance of AI-related content.

Guidelines:
- Create a compelling title (5-10 words) that captures the essence of the content
- Write a 2-3 sentence summary that highlights the main points and why they matter
- Focus on actionable insights and implications
- Use clear, accessible language while maintaining technical accuracy
- Avoid marketing fluff - focus on substance"""


class DigestOutput(BaseModel):
    title: str
    summary: str


class DigestAgent:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url=_GEMINI_URL)
        self.model = _MODEL

    def generate_digest(self, title: str, content: str, article_type: str) -> Optional[DigestOutput]:
        user_prompt = (
            f"Create a digest for this {article_type}: \n Title: {title} \n Content: {content[:8000]}\n\n"
            'Return a JSON object with exactly: {"title": "...", "summary": "..."}'
        )
        try:
            tracker.record_api_call()
            time.sleep(_RATE_LIMIT_SLEEP)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": _PROMPT}, {"role": "user", "content": user_prompt}],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            result = DigestOutput.model_validate_json(response.choices[0].message.content)
            tracker.record_validation_success()
            return result
        except ValidationError:
            tracker.record_validation_failure()
            return None
        except Exception as e:
            print(f"Error generating digest: {e}")
            return None
