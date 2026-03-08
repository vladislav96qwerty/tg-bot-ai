import asyncio
import json
import logging
from typing import Any, Dict, Optional, Union

from google import genai
from groq import AsyncGroq

from src.config import config

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self):
        self.groq_client = AsyncGroq(api_key=config.GROQ_API_KEY, timeout=8.0)
        self.gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)

    async def ask(
        self, prompt: str, expect_json: bool = True
    ) -> Union[Dict[str, Any], str, None]:
        """
        Main method to get AI response.
        First tries Groq (Llama 3.3 70B), then falls back to Gemini 2.0 Flash.
        """
        try:
            logger.info("Requesting Groq Llama 3.3...")
            response = await self._ask_groq(prompt, expect_json)
            if response is not None:
                logger.info("Success using Groq")
                return response
        except Exception as e:
            logger.error(f"Groq API error: {e}")

        try:
            logger.info("Requesting Gemini 2.0 Flash (fallback)...")
            response = await self._ask_gemini(prompt, expect_json)
            if response is not None:
                logger.info("Success using Gemini fallback")
                return response
        except Exception as e:
            logger.error(f"Gemini API error: {e}")

        logger.error("Both AI services failed.")
        return None

    async def _ask_groq(self, prompt: str, expect_json: bool) -> Any:
        response_format = {"type": "json_object"} if expect_json else None

        chat_completion = await self.groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            response_format=response_format,
        )
        content = chat_completion.choices[0].message.content
        return self._parse_json(content) if expect_json else content

    async def _ask_gemini(self, prompt: str, expect_json: bool) -> Any:
        if expect_json and "JSON" not in prompt:
            prompt += "\n\nProvide response in strict JSON format."

        response = await asyncio.to_thread(
            self.gemini_client.models.generate_content,
            model="gemini-1.5-flash",
            contents=prompt,
        )
        content = response.text

        if expect_json:
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        return self._parse_json(content) if expect_json else content

    def _parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}. Content: {content}")
            return None


# Global instance
ai_service = AIService()