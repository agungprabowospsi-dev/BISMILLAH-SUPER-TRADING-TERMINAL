import os
import httpx
import logging

logger = logging.getLogger(__name__)
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

async def ask_claude(system: str, prompt: str, max_tokens: int = 300) -> str:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5",
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                }
            )
            r.raise_for_status()
            data = r.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return "AI analysis temporarily unavailable."
