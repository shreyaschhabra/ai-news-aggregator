import os
import smtplib
import logging
import html as html_lib
import markdown as md_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from app.stats_tracker import tracker

load_dotenv()

MY_EMAIL = os.getenv("MY_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

logger = logging.getLogger(__name__)

_MD_EXTENSIONS = ["extra", "nl2br"]

_EMAIL_CSS = """
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        line-height: 1.6; color: #333; max-width: 600px;
        margin: 0 auto; padding: 20px; background-color: #ffffff;
    }
    h2 { font-size: 18px; font-weight: 600; color: #1a1a1a; margin-top: 24px; margin-bottom: 8px; line-height: 1.4; }
    h3 { font-size: 16px; font-weight: 600; color: #1a1a1a; margin-top: 20px; margin-bottom: 8px; line-height: 1.4; }
    p, div { margin: 8px 0; color: #4a4a4a; }
    strong { font-weight: 600; color: #1a1a1a; }
    em { font-style: italic; color: #666; }
    a { color: #0066cc; text-decoration: none; font-weight: 500; }
    a:hover { text-decoration: underline; }
    hr { border: none; border-top: 1px solid #e5e5e5; margin: 20px 0; }
    .greeting { font-size: 16px; font-weight: 500; color: #1a1a1a; margin-bottom: 12px; }
    .greeting p, .introduction p { margin: 0; }
    .introduction { color: #4a4a4a; margin-bottom: 20px; }
    .article-link { display: inline-block; margin-top: 8px; color: #0066cc; font-size: 14px; }
    div p { margin: 4px 0; }"""


def _html_page(body_content: str) -> str:
    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'<style>{_EMAIL_CSS}</style>'
        f'</head><body>{body_content}</body></html>'
    )


def send_email(subject: str, body_text: str, body_html: str = None, recipients: list = None):
    if not MY_EMAIL:
        raise ValueError("MY_EMAIL environment variable is not set")
    if not APP_PASSWORD:
        raise ValueError("APP_PASSWORD environment variable is not set")

    if recipients is None:
        recipients = [MY_EMAIL]
    recipients = [r for r in recipients if r]
    if not recipients:
        raise ValueError("No valid recipients provided")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MY_EMAIL
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(MY_EMAIL, APP_PASSWORD)
        smtp.sendmail(MY_EMAIL, recipients, msg.as_string())


def markdown_to_html(markdown_text: str) -> str:
    return _html_page(md_lib.markdown(markdown_text, extensions=_MD_EXTENSIONS))


def digest_to_html(digest_response) -> str:
    from app.agent.email_agent import EmailDigestResponse

    if not isinstance(digest_response, EmailDigestResponse):
        return markdown_to_html(
            digest_response.to_markdown() if hasattr(digest_response, "to_markdown") else str(digest_response)
        )

    parts = [
        f'<div class="greeting">{md_lib.markdown(digest_response.introduction.greeting, extensions=_MD_EXTENSIONS)}</div>',
        f'<div class="introduction">{md_lib.markdown(digest_response.introduction.introduction, extensions=_MD_EXTENSIONS)}</div>',
        "<hr>",
    ]
    for article in digest_response.articles:
        parts += [
            f'<h3>{html_lib.escape(article.title)}</h3>',
            f'<div>{md_lib.markdown(article.summary, extensions=_MD_EXTENSIONS)}</div>',
            f'<p><a href="{html_lib.escape(article.url)}" class="article-link">Read more →</a></p>',
            "<hr>",
        ]
    return _html_page("\n".join(parts))


# --- Email digest generation (pipeline step 5) ---

def generate_email_digest(hours: int = 24, top_n: int = 10):
    from app.agent.email_agent import EmailAgent, RankedArticleDetail, EmailDigestResponse
    from app.agent.curator_agent import CuratorAgent
    from app.config import USER_PROFILE
    from app.database.repository import Repository

    curator = CuratorAgent(USER_PROFILE)
    email_agent = EmailAgent(USER_PROFILE)
    repo = Repository()

    digests = repo.get_recent_digests(hours=hours)
    if not digests:
        logger.warning(f"No digests found from the last {hours} hours")
        raise ValueError("No digests available")

    tracker.record_articles_evaluated(len(digests))
    logger.info(f"Ranking {len(digests)} digests for email generation")
    ranked_articles = curator.rank_digests(digests)
    if not ranked_articles:
        logger.error("Failed to rank digests")
        raise ValueError("Failed to rank articles")

    logger.info(f"Generating email digest with top {top_n} articles")
    digest_map = {d["id"]: d for d in digests}
    article_details = [
        RankedArticleDetail(
            digest_id=a.digest_id,
            rank=a.rank,
            relevance_score=a.relevance_score,
            reasoning=a.reasoning,
            title=digest_map.get(a.digest_id, {}).get("title", ""),
            summary=digest_map.get(a.digest_id, {}).get("summary", ""),
            url=digest_map.get(a.digest_id, {}).get("url", ""),
            article_type=digest_map.get(a.digest_id, {}).get("article_type", ""),
        )
        for a in ranked_articles
    ]

    email_digest = email_agent.create_email_digest_response(
        ranked_articles=article_details, total_ranked=len(ranked_articles), limit=top_n
    )
    logger.info(f"Email digest generated: {email_digest.introduction.greeting}")
    return email_digest


def send_digest_email(hours: int = 24, top_n: int = 10) -> dict:
    try:
        result = generate_email_digest(hours=hours, top_n=top_n)
        greeting = result.introduction.greeting
        subject = f"Daily AI News Digest - {greeting.split('for ')[-1] if 'for ' in greeting else 'Today'}"
        send_email(subject=subject, body_text=result.to_markdown(), body_html=digest_to_html(result))
        logger.info("Email sent successfully!")
        return {"success": True, "subject": subject, "articles_count": len(result.articles)}
    except ValueError as e:
        logger.error(f"Error sending email: {e}")
        return {"success": False, "error": str(e)}
