import os
import asyncio
import httpx
import logging

logger = logging.getLogger(__name__)
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Global semaphore — max 2 concurrent Claude calls sekaligus
_claude_semaphore = asyncio.Semaphore(2)

async def ask_claude(system: str, prompt: str, max_tokens: int = 300) -> str:
    async with _claude_semaphore:
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
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                )
                if r.status_code != 200:
                    logger.error(f"Claude API {r.status_code}: {r.text}")
                    return "AI analysis temporarily unavailable."
                data = r.json()
                return data["content"][0]["text"].strip()
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return "AI analysis temporarily unavailable."
# model: claude-haiku-4-5-20251001
