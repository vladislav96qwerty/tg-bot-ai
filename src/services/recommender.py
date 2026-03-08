import asyncio
import logging
from typing import List, Dict, Any, Optional

from src.database.db import db
from src.services.ai import ai_service
from src.services.tmdb import tmdb_service
from src.services.prompts import RECOMMENDATION_PROMPT

logger = logging.getLogger(__name__)

class RecommenderService:
    async def get_recommendations(self, user_id: int, mood: str = "спокійний") -> List[Dict[str, Any]]:
        """Generates AI recommendations based on user history and preferences."""
        
        # 1. Collect User Context
        prefs = await db.get_user_preferences(user_id)
        if not prefs:
            return [] # Should not happen if onboarding is done
            
        ratings_summary = await db.get_user_ratings_summary(user_id)
        watched_titles = await db.get_watched_titles(user_id)
        
        # 2. Prepare Prompt
        prompt = RECOMMENDATION_PROMPT.format(
            genres=prefs.get("genres", "будь-які"),
            watched_titles=", ".join(watched_titles) if watched_titles else "нічого",
            avg_rating=ratings_summary.get("avg", 0),
            liked_titles=", ".join(ratings_summary.get("liked", [])) if ratings_summary.get("liked") else "немає",
            disliked_titles=", ".join(ratings_summary.get("disliked", [])) if ratings_summary.get("disliked") else "немає",
            fav_decade=prefs.get("fav_period", "будь-який"),
            mood=mood
        )
        
        # 3. Get AI Response
        ai_response = await ai_service.ask(prompt, expect_json=True)
        if not ai_response or "recommendations" not in ai_response:
            logger.error("AI failed to provide recommendations")
            return []
            
        async def enrich_rec(rec):
            # 4. Enrich with TMDB data (ID and Poster)
            search_results = await tmdb_service.search_movies(rec["title"], limit=1)
            if not search_results:
                # Try with title_ua
                search_results = await tmdb_service.search_movies(rec["title_ua"], limit=1)
            
            if search_results:
                movie_data = search_results[0]
                rec["tmdb_id"] = movie_data.get("id")
                rec["poster_path"] = movie_data.get("poster_path")
                rec["tmdb_rating"] = movie_data.get("vote_average")
            else:
                rec["tmdb_id"] = None
                rec["poster_path"] = None
                rec["tmdb_rating"] = 0
            return rec

        tasks = [enrich_rec(rec) for rec in ai_response["recommendations"]]
        final_recs = await asyncio.gather(*tasks)
            
        return final_recs

recommender_service = RecommenderService()
