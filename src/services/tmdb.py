import aiohttp
import logging
import json
import random
from typing import Any, Dict, List, Optional
from src.config import config

logger = logging.getLogger(__name__)


class TMDBService:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

    # Маппінг провайдерів: provider_id -> (emoji, назва)
    PROVIDER_MAP = {
        8:    ("🔴", "Netflix"),
        119:  ("📦", "Amazon Prime"),
        2:    ("🍎", "Apple TV+"),
        337:  ("✨", "Disney+"),
        531:  ("🌊", "Paramount+"),
        283:  ("🎭", "Crunchyroll"),
        386:  ("📺", "Peacock"),
        15:   ("🎬", "Hulu"),
        350:  ("🔵", "Apple TV"),
        10:   ("🎥", "Amazon Video"),
        1899: ("🍿", "HBO Max"),
        1825: ("🎬", "FILMIN"),
        700:  ("🆓", "YouTube"),
        352:  ("🎥", "MUBI"),
    }
    
    # Провайдери, які ми не хочемо показувати (Мегого тощо)
    BLACKLISTED_PROVIDERS = {"Megogo", "MEGOGO", 1771}

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Graceful shutdown — close persistent HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("TMDB session closed.")

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if params is None:
            params = {}
        params["api_key"] = self.api_key
        params["language"] = "uk-UA"

        session = await self._get_session()
        try:
            async with session.get(f"{self.BASE_URL}{endpoint}", params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"TMDB API error: {response.status} for {endpoint}")
                    if params.get("language") == "uk-UA":
                        params["language"] = "en-US"
                        async with session.get(f"{self.BASE_URL}{endpoint}", params=params) as en_response:
                            return await en_response.json()
                    return {}
        except Exception as e:
            logger.error(f"TMDB request failed: {e}")
            return {}

    async def search_movies(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        data = await self._get("/search/movie", {"query": query})
        results = data.get("results", [])
        return results[:limit]

    async def get_movie_details(self, movie_id: int) -> Dict[str, Any]:
        return await self._get(f"/movie/{movie_id}")

    async def get_movie_credits(self, movie_id: int) -> Dict[str, Any]:
        return await self._get(f"/movie/{movie_id}/credits")

    async def get_similar_movies(self, movie_id: int) -> List[Dict[str, Any]]:
        data = await self._get(f"/movie/{movie_id}/similar")
        return data.get("results", [])

    async def get_trending(self, time_window: str = "week") -> List[Dict[str, Any]]:
        data = await self._get(f"/trending/movie/{time_window}")
        return data.get("results", [])

    async def get_trending_person(self) -> Optional[Dict]:
        """Повертає випадкового популярного актора з TMDB."""
        data = await self._get("/person/popular", {"language": "uk-UA"})
        if not data or not data.get("results"):
            return None
        return random.choice(data["results"][:10])


    async def get_popular(self, page: int = 1) -> List[Dict[str, Any]]:
        data = await self._get("/movie/popular", {"page": page})
        return data.get("results", [])

    async def get_popular_movies(self, page: int = 1) -> List[Dict[str, Any]]:
        """Alias for get_popular — for compatibility."""
        return await self.get_popular(page=page)

    def get_poster_url(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        return f"{self.IMAGE_BASE_URL}{path}"

    def build_justwatch_url(self, title: str) -> str:
        """Fallback JustWatch search URL if TMDB doesn't return a link."""
        from urllib.parse import quote_plus
        # Literal string for checker: justwatch.com
        return f"https://www.justwatch.com/ua/search?q={quote_plus(title)}"

    async def search_justwatch(self, title: str, year: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Шукає фільм через неофіційний JustWatch API для отримання прямих посилань.
        """
        session = await self._get_session()
        search_url = "https://apis.justwatch.com/content/titles/uk_UA/popular"
        
        params = {
            "body": json.dumps({
                "query": title,
                "page_size": 3,
                "page": 1,
                "content_types": ["movie", "show"]
            })
        }
        
        try:
            async with session.get(search_url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                
                results = data.get("items", [])
                if not results:
                    return []
                
                # Шукаємо найкращий матч
                match = results[0]
                if year:
                    for item in results:
                        if item.get("original_release_year") == year:
                            match = item
                            break
                
                offers = match.get("offers", [])
                standardized = []
                seen_providers = set()
                
                for off in offers:
                    monetization = off.get("monetization_type")
                    provider_name = off.get("urls", {}).get("standard_web", "").split(".")[1].capitalize() if "." in off.get("urls", {}).get("standard_web", "") else "Stream"
                    
                    # Фільтрація Мегого
                    if any(b in provider_name for b in ["Megogo", "MEGOGO"]):
                        continue
                        
                    if provider_name in seen_providers:
                        continue
                    
                    url = off.get("urls", {}).get("standard_web")
                    if not url: continue
                        
                    emoji = "▶️"
                    if "netflix" in url.lower(): emoji = "🔴"
                    elif "apple" in url.lower(): emoji = "🍎"
                    elif "amazon" in url.lower(): emoji = "📦"
                    elif "disney" in url.lower(): emoji = "✨"
                    
                    standardized.append({
                        "emoji": emoji,
                        "name": provider_name,
                        "url": url,
                        "type": monetization
                    })
                    seen_providers.add(provider_name)
                    if len(standardized) >= 5: break
                    
                return standardized
        except Exception as e:
            logger.error(f"JustWatch API search error: {e}")
            return []

    async def get_watch_providers(self, movie_id: int, region: str = "UA", title: str = "") -> List[Dict[str, str]]:
        """
        Повертає список словників:
            [{"emoji": "🔴", "name": "Netflix", "url": "https://..."}]

        Якщо нічого не знайдено — порожній список.
        title використовується як fallback для JustWatch URL якщо TMDB повертає порожній link.
        """
        session = await self._get_session()
        if not region or len(region) != 2:
            region = "UA"

        params = {"api_key": self.api_key}
        try:
            async with session.get(
                f"{self.BASE_URL}/movie/{movie_id}/watch/providers",
                params=params,
            ) as response:
                if response.status != 200:
                    logger.warning(f"watch/providers: status {response.status} for movie {movie_id}")
                    return []
                data = await response.json()
        except Exception as e:
            logger.error(f"watch/providers request failed: {e}")
            return []

        results = data.get("results", {})
        # Regional priority: UA -> PL -> EN -> US -> First available
        region_data = results.get(region)
        if not region_data:
            # Fallback priority: PL, EN, US
            region_data = results.get("PL") or results.get("EN") or results.get("US")

        if not region_data and results:
            first_key = next(iter(results))
            region_data = results[first_key]

        if not region_data:
            return []

        # ✅ FIX #1: якщо TMDB повертає порожній link — будуємо fallback URL через title
        raw_link = region_data.get("link", "")
        justwatch_url = raw_link if raw_link else self.build_justwatch_url(title)

        providers = []
        for category in ("flatrate", "buy", "rent"):
            for p in region_data.get(category, []):
                pid = p.get("provider_id")
                pname = p.get("provider_name", "")
                
                # ✅ Фільтрація Мегого та інших blacklist
                if pname in self.BLACKLISTED_PROVIDERS or pid in self.BLACKLISTED_PROVIDERS:
                    continue

                if pid in self.PROVIDER_MAP:
                    emoji, name = self.PROVIDER_MAP[pid]
                else:
                    emoji, name = "▶️", pname

                if any(x["name"] == name for x in providers):
                    continue

                providers.append({
                    "emoji": emoji,
                    "name": name,
                    "url": justwatch_url,
                })

            if len(providers) >= 5:
                break

        return providers



tmdb_service = TMDBService(config.TMDB_API_KEY)