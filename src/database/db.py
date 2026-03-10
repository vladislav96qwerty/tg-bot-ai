import libsql_client
import collections.abc
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from src.database.schema import ALL_TABLES
from src.config import config

logger = logging.getLogger(__name__)

# --- LibSQL Shim Classes (Адаптер для обратной совместимости aiosqlite -> libsql) ---
class ShimRow(collections.abc.Mapping):
    def __init__(self, columns, values):
        self._cols = columns
        self._vals = values
        self._dict = dict(zip(columns, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._dict[key]

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)
    
    def keys(self):
        return self._dict.keys()

class LibsqlCursor:
    def __init__(self, result):
        self.result = result
        self._rows = [ShimRow(result.columns, r) for r in result.rows]
        self._idx = 0

    async def fetchone(self):
        if self._idx < len(self._rows):
            r = self._rows[self._idx]
            self._idx += 1
            return r
        return None

    async def fetchall(self):
        res = self._rows[self._idx:]
        self._idx = len(self._rows)
        return res

class LibsqlCursorContext:
    def __init__(self, client, query, parameters):
        self._client = client
        self._query = query
        self._parameters = parameters
        self._cursor = None

    def __await__(self):
        async def _do_execute():
            result = await self._client.execute(self._query, self._parameters)
            self._cursor = LibsqlCursor(result)
            return self._cursor
        return _do_execute().__await__()

    async def __aenter__(self):
        result = await self._client.execute(self._query, self._parameters)
        self._cursor = LibsqlCursor(result)
        return self._cursor

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class LibsqlConnectionShim:
    def __init__(self, client):
        self._client = client

    def execute(self, query: str, parameters: tuple = ()):
        return LibsqlCursorContext(self._client, query, parameters)

    async def commit(self):
        pass

    async def close(self):
        await self._client.close()
# -----------------------------------------------------------------------------------

class Database:
    def __init__(self, db_path: str = "bot_database.db"):
        self.db_path = db_path
        self._db: LibsqlConnectionShim | None = None

    async def _get_db(self) -> LibsqlConnectionShim:
        if self._db is None:
            if config.TURSO_DATABASE_URL and config.TURSO_AUTH_TOKEN:
                url = config.TURSO_DATABASE_URL
                if url.startswith("libsql://"):
                    url = url.replace("libsql://", "https://")
                client = libsql_client.create_client(
                    url=url,
                    auth_token=config.TURSO_AUTH_TOKEN
                )
                logger.info("Connected to Turso Cloud DB (via HTTPS)")

            else:
                client = libsql_client.create_client(f"file:{self.db_path}")
                logger.info(f"Connected to local SQLite DB ({self.db_path}) via libsql")
            self._db = LibsqlConnectionShim(client)
        return self._db

    async def close(self):
        """Graceful shutdown"""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("Database connection closed.")

    async def _execute(self, query: str, params: tuple = ()) -> Any:
        db = await self._get_db()
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchall()
            await db.commit()
            return result

    async def _add_column_if_missing(self, db, table: str, column: str, definition: str):
        """Безпечно додає колонку якщо вона ще не існує."""
        async with db.execute(f"PRAGMA table_info({table})") as cursor:
            cols = [row[1] for row in await cursor.fetchall()]
        if column not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            await db.commit()
            logger.info(f"Migration: added column {table}.{column}")

    async def init_db(self):
        """Ініціалізує БД та запускає міграції."""
        db = await self._get_db()
        for table_query in ALL_TABLES:
            await db.execute(table_query)
        await db.commit()

        # РњС–РіСЂР°С†С–С— вЂ” Р±РµР·РїРµС‡РЅС–
        await self._add_column_if_missing(db, "channel_posts", "content", "TEXT")
        await self._add_column_if_missing(db, "users", "points", "INTEGER DEFAULT 0")
        await self._add_column_if_missing(db, "users", "last_active", "TIMESTAMP")
        await self._add_column_if_missing(db, "users", "notifications_enabled", "INTEGER DEFAULT 1")
        # v2.0 — нові колонки для ban/note
        await self._add_column_if_missing(db, "users", "is_banned", "INTEGER DEFAULT 0")
        await self._add_column_if_missing(db, "users", "ban_reason", "TEXT")
        await self._add_column_if_missing(db, "users", "admin_note", "TEXT")
        # ✅ FIX #2: channel_member_status для коректного кешування is_premium
        await self._add_column_if_missing(db, "users", "channel_member_status", "TEXT DEFAULT 'unknown'")

        # Р†РЅРґРµРєСЃРё РґР»СЏ РїСЂРѕРґСѓРєС‚РёРІРЅРѕСЃС‚С–
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_watchlist_user_tmdb ON watchlist(user_id, tmdb_id)",
            "CREATE INDEX IF NOT EXISTS idx_ratings_user ON ratings(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_ratings_user_tmdb ON ratings(user_id, tmdb_id)",
            "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",
            "CREATE INDEX IF NOT EXISTS idx_poll_votes_user ON poll_votes(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_poll_votes_poll ON poll_votes(poll_id)",
            "CREATE INDEX IF NOT EXISTS idx_channel_posts_type ON channel_posts(post_type, posted_at)",
            "CREATE INDEX IF NOT EXISTS idx_achievements_user ON achievements(user_id)",
        ]
        for idx in indexes:
            await db.execute(idx)
        await db.commit()

        logger.info("Database initialized successfully.")

    # в”Ђв”Ђ Channel Posts в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def save_channel_post(self, post_type: str, preview_text: str, content: str, tmdb_id: Optional[int] = None, message_id: Optional[int] = None):
        """Р›РѕРіСѓС” РїРѕСЃС‚ РЅР°РґС–СЃР»Р°РЅРёР№ Сѓ РєР°РЅР°Р»."""
        query = """
        INSERT INTO channel_posts (post_type, preview_text, content, tmdb_id, message_id)
        VALUES (?, ?, ?, ?, ?)
        """
        await self._execute(query, (post_type, preview_text, content, tmdb_id, message_id))

    # Р’РРџР РђР’Р›Р•РќРћ: РѕРєСЂРµРјРёР№ РјРµС‚РѕРґ РґР»СЏ JSON-РєРµС€Сѓ РґРѕР±С–СЂРєРё (РІС–РґРѕРєСЂРµРјР»РµРЅРѕ РІС–Рґ С‚РµРєСЃС‚РѕРІРёС… РїРѕСЃС‚С–РІ)
    async def save_daily_picks_cache(self, content_json: str):
        """
        Р—Р±РµСЂС–РіР°С” JSON РґРѕР±С–СЂРєРё Р· post_type='daily_picks_cache'.
        Р’С–РґРѕРєСЂРµРјР»РµРЅРѕ РІС–Рґ save_channel_post С‰РѕР± СѓРЅРёРєРЅСѓС‚Рё РїР»СѓС‚Р°РЅРёРЅРё С„РѕСЂРјР°С‚С–РІ:
        - 'daily_picks' (Р· РїР»Р°РЅСѓРІР°Р»СЊРЅРёРєР°) вЂ” content = РіРѕС‚РѕРІРёР№ С‚РµРєСЃС‚
        - 'daily_picks_cache' (С†РµР№ РјРµС‚РѕРґ) вЂ” content = JSON СЂСЏРґРѕРє
        """
        query = """
        INSERT INTO channel_posts (post_type, preview_text, content)
        VALUES ('daily_picks_cache', 'cache', ?)
        """
        await self._execute(query, (content_json,))

    async def get_recent_daily_picks_cache(self):
        """РџРѕРІРµСЂС‚Р°С” JSON-РєРµС€ РґРѕР±С–СЂРєРё СЏРєС‰Рѕ РІС–РЅ СЃРІС–Р¶РёР№ (< 24 РіРѕРґ)."""
        query = """
        SELECT * FROM channel_posts
        WHERE post_type = 'daily_picks_cache'
        AND posted_at > datetime('now', '-24 hours')
        ORDER BY posted_at DESC LIMIT 1
        """
        db = await self._get_db()
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_recent_post_by_type(self, post_type: str) -> Optional[Dict]:
        """Повертає останній пост заданого типу."""
        query = "SELECT * FROM channel_posts WHERE post_type = ? ORDER BY posted_at DESC LIMIT 1"
        db = await self._get_db()
        async with db.execute(query, (post_type,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    # Р—Р°Р»РёС€Р°С”РјРѕ РґР»СЏ Р·РІРѕСЂРѕС‚РЅРѕС— СЃСѓРјС–СЃРЅРѕСЃС‚С– (РІРёРєРѕСЂРёСЃС‚РѕРІСѓС”С‚СЊСЃСЏ РІ scheduler.py)
    # в”Ђв”Ђ User Management в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def get_user(self, user_id: int):
        db = await self._get_db()
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get(self, user_id: int):
        """Alias for get_user."""
        return await self.get_user(user_id)

    async def create_user(self, user_id: int, username: str, full_name: str, language_code: str):
        query = """
        INSERT INTO users (user_id, username, full_name, language_code)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name
        """
        await self._execute(query, (user_id, username, full_name, language_code))

    async def update_user(self, user_id: int, **kwargs):
        if not kwargs:
            return
        # Р—Р°РІР¶РґРё РѕРЅРѕРІР»СЋС”РјРѕ last_active СЂР°Р·РѕРј Р· Р±СѓРґСЊ-СЏРєРёРј РѕРЅРѕРІР»РµРЅРЅСЏРј
        kwargs["last_active"] = datetime.now().isoformat()
        columns = ", ".join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values())
        values.append(user_id)
        query = f"UPDATE users SET {columns} WHERE user_id = ?"
        await self._execute(query, tuple(values))

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM users WHERE username = ?"
        db = await self._get_db()
        async with db.execute(query, (username,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_all_users(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM users"
        db = await self._get_db()
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_active_users_count(self, hours: int = 24) -> int:
        query = "SELECT COUNT(*) FROM users WHERE last_active > datetime('now', ?)"
        param = f"-{hours} hours"
        db = await self._get_db()
        async with db.execute(query, (param,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # в”Ђв”Ђ User Preferences в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def get_user_preferences(self, user_id: int) -> Optional[Dict[str, Any]]:
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_user_preferences(self, user_id: int, genres: List[str], frequency: str, period: str):
        query = """
        INSERT INTO user_preferences (user_id, genres, view_frequency, fav_period)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            genres = excluded.genres,
            view_frequency = excluded.view_frequency,
            fav_period = excluded.fav_period
        """
        await self._execute(query, (user_id, ",".join(genres), frequency, period))

    async def update_user_preferences(self, user_id: int, **kwargs):
        if not kwargs:
            return
        columns = ", ".join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values())
        values.append(user_id)
        query = f"UPDATE user_preferences SET {columns} WHERE user_id = ?"
        await self._execute(query, tuple(values))

    # в”Ђв”Ђ Watchlist в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def get_watchlist_count(self, user_id: int) -> int:
        query = "SELECT COUNT(*) FROM watchlist WHERE user_id = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def add_to_watchlist(self, user_id: int, tmdb_id: int, title_ua: str, status: str = "want"):
        check_query = "SELECT id FROM watchlist WHERE user_id = ? AND tmdb_id = ?"
        db = await self._get_db()
        async with db.execute(check_query, (user_id, tmdb_id)) as cursor:
            exists = await cursor.fetchone()
            if exists:
                await db.execute(
                    "UPDATE watchlist SET status = ? WHERE user_id = ? AND tmdb_id = ?",
                    (status, user_id, tmdb_id),
                )
            else:
                await db.execute(
                    "INSERT INTO watchlist (user_id, tmdb_id, title_ua, status) VALUES (?, ?, ?, ?)",
                    (user_id, tmdb_id, title_ua, status),
                )
        await db.commit()

    async def get_watchlist(self, user_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM watchlist WHERE user_id = ?"
        params: List[Any] = [user_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY added_at DESC"
        db = await self._get_db()
        async with db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_watchlist_item(self, user_id: int, tmdb_id: int):
        """РџРѕРІРµСЂС‚Р°С” РѕРґРёРЅ РµР»РµРјРµРЅС‚ РІРѕС‚С‡Р»С–СЃС‚Р° Р·Р° tmdb_id (Р±РµР· Р·Р°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ РІСЃСЊРѕРіРѕ СЃРїРёСЃРєСѓ)."""
        query = "SELECT * FROM watchlist WHERE user_id = ? AND tmdb_id = ? LIMIT 1"
        db = await self._get_db()
        async with db.execute(query, (user_id, tmdb_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_watchlist_status(self, user_id: int, tmdb_id: int, new_status: str):
        query = "UPDATE watchlist SET status = ? WHERE user_id = ? AND tmdb_id = ?"
        await self._execute(query, (new_status, user_id, tmdb_id))

    async def delete_from_watchlist(self, user_id: int, tmdb_id: int):
        query = "DELETE FROM watchlist WHERE user_id = ? AND tmdb_id = ?"
        await self._execute(query, (user_id, tmdb_id))

    # в”Ђв”Ђ Ratings в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def add_rating(self, user_id: int, tmdb_id: int, rating: int):
        check_query = "SELECT id FROM ratings WHERE user_id = ? AND tmdb_id = ?"
        db = await self._get_db()
        async with db.execute(check_query, (user_id, tmdb_id)) as cursor:
            exists = await cursor.fetchone()
            if exists:
                await db.execute(
                    "UPDATE ratings SET rating = ? WHERE user_id = ? AND tmdb_id = ?",
                    (rating, user_id, tmdb_id),
                )
            else:
                await db.execute(
                    "INSERT INTO ratings (user_id, tmdb_id, rating) VALUES (?, ?, ?)",
                    (user_id, tmdb_id, rating),
                )
        await db.commit()

    async def get_movie_rating(self, user_id: int, tmdb_id: int) -> Optional[int]:
        query = "SELECT rating FROM ratings WHERE user_id = ? AND tmdb_id = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id, tmdb_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_user_ratings_list(self, user_id: int) -> List[Dict[str, Any]]:
        """РџРѕРІРµСЂС‚Р°С” РІСЃС– РѕС†С–РЅРєРё СЋР·РµСЂР° Р· РЅР°Р·РІР°РјРё С„С–Р»СЊРјС–РІ."""
        query = """
        SELECT r.tmdb_id, r.rating,
               COALESCE(w.title_ua, 'TMDB#' || r.tmdb_id) as title_ua
        FROM ratings r
        LEFT JOIN watchlist w ON r.user_id = w.user_id AND r.tmdb_id = w.tmdb_id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        """
        db = await self._get_db()
        async with db.execute(query, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_user_stats(self, user_id: int):
        """РџРѕРІРµСЂС‚Р°С” СЃС‚Р°С‚РёСЃС‚РёРєСѓ СЋР·РµСЂР° РґР»СЏ РїСЂРѕС„С–Р»СЋ."""
        db = await self._get_db()

        async with db.execute(
            "SELECT COUNT(*) FROM watchlist WHERE user_id = ? AND status = 'watched'",
            (user_id,),
        ) as c:
            row = await c.fetchone()
            watched_count = row[0] if row else 0

        async with db.execute(
            "SELECT COUNT(*) FROM watchlist WHERE user_id = ?", (user_id,)
        ) as c:
            row = await c.fetchone()
            watchlist_count = row[0] if row else 0

        async with db.execute(
            "SELECT COUNT(*), AVG(rating) FROM ratings WHERE user_id = ?", (user_id,)
        ) as c:
            row = await c.fetchone()
            ratings_count = row[0] if row else 0
            avg_rating = round(row[1], 1) if row and row[1] else 0

        query_top = """
        SELECT user_id, COUNT(DISTINCT tmdb_id) as total_score
        FROM (
            SELECT user_id, tmdb_id FROM ratings
            UNION
            SELECT user_id, tmdb_id FROM watchlist WHERE status = 'watched'
        )
        GROUP BY user_id
        ORDER BY total_score DESC
        """
        async with db.execute(query_top) as c:
            rows = await c.fetchall()
            top_position = next(
                (i + 1 for i, row in enumerate(rows) if row["user_id"] == user_id),
                len(rows) + 1,
            )

        saved_quotes_count = await self.get_saved_quotes_count(user_id)

        return {
            "watched_count": watched_count,
            "watchlist_count": watchlist_count,
            "ratings_count": ratings_count,
            "avg_rating": avg_rating,
            "top_position": top_position,
            "saved_quotes_count": saved_quotes_count,
        }

    # в”Ђв”Ђ Recommendations в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def get_user_ratings_summary(self, user_id: int):
        db = await self._get_db()

        async with db.execute(
            "SELECT AVG(rating) FROM ratings WHERE user_id = ?", (user_id,)
        ) as c:
            row = await c.fetchone()
            avg = round(row[0], 1) if row and row[0] else 0

        async with db.execute(
            """SELECT w.title_ua FROM ratings r
               JOIN watchlist w ON r.user_id = w.user_id AND r.tmdb_id = w.tmdb_id
               WHERE r.user_id = ? AND r.rating >= 8""",
            (user_id,),
        ) as c:
            liked = [row["title_ua"] for row in await c.fetchall()]

        async with db.execute(
            """SELECT w.title_ua FROM ratings r
               JOIN watchlist w ON r.user_id = w.user_id AND r.tmdb_id = w.tmdb_id
               WHERE r.user_id = ? AND r.rating <= 5""",
            (user_id,),
        ) as c:
            disliked = [row["title_ua"] for row in await c.fetchall()]

        return {"avg": avg, "liked": liked, "disliked": disliked}

    async def get_watched_titles(self, user_id: int):
        db = await self._get_db()
        async with db.execute(
            "SELECT title_ua FROM watchlist WHERE user_id = ? AND status = 'watched'",
            (user_id,),
        ) as c:
            rows = await c.fetchall()
            return [row[0] for row in rows]

    # в”Ђв”Ђ Referrals в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def add_referral(self, referrer_id: int, referred_id: int):
        check_query = "SELECT id FROM referrals WHERE referred_id = ?"
        db = await self._get_db()
        async with db.execute(check_query, (referred_id,)) as cursor:
            if not await cursor.fetchone():
                await db.execute(
                    "INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                    (referrer_id, referred_id),
                )
                await db.commit()

    async def get_referral_count(self, user_id: int):
        query = "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # в”Ђв”Ђ Admin Stats в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def get_admin_stats(self):
        db = await self._get_db()
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            row = await c.fetchone()
            total_users = row[0] if row else 0
        async with db.execute("SELECT COUNT(*) FROM watchlist") as c:
            row = await c.fetchone()
            total_watchlist = row[0] if row else 0
        async with db.execute("SELECT COUNT(*) FROM ratings") as c:
            row = await c.fetchone()
            total_ratings = row[0] if row else 0
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_sponsor = 1") as c:
            row = await c.fetchone()
            total_sponsors = row[0] if row else 0
        return {
            "total_users": total_users,
            "total_watchlist": total_watchlist,
            "total_ratings": total_ratings,
            "total_sponsors": total_sponsors,
        }

    async def get_weekly_stats(self):
        """Р—РІРµРґРµРЅР° СЃС‚Р°С‚РёСЃС‚РёРєР° Р·Р° 7 РґРЅС–РІ РґР»СЏ WEEKLY_SUMMARY_PROMPT."""
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        db = await self._get_db()

        async with db.execute(
            "SELECT COUNT(*) FROM channel_posts WHERE posted_at >= ? AND post_type != 'daily_picks_cache'",
            (week_ago,),
        ) as c:
            row = await c.fetchone()
            films_count = row[0] if row else 0

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?", (week_ago,)
        ) as c:
            row = await c.fetchone()
            new_subs = row[0] if row else 0

        async with db.execute(
            "SELECT full_name FROM users ORDER BY points DESC LIMIT 1"
        ) as c:
            row = await c.fetchone()
            top_user = row["full_name"] if row else "РќРµРІС–РґРѕРјРѕ"

        async with db.execute(
            """SELECT p.movie_a_id, p.movie_b_id, pv.option_voted, COUNT(*) as cnt
               FROM poll_votes pv
               JOIN polls p ON p.poll_id = pv.poll_id
               WHERE p.ends_at >= ?
               GROUP BY pv.poll_id, pv.option_voted
               ORDER BY cnt DESC
               LIMIT 1""",
            (week_ago,),
        ) as c:
            row = await c.fetchone()
            if row:
                winner_id = row["movie_a_id"] if row["option_voted"] == 0 else row["movie_b_id"]
                poll_winner = f"TMDB#{winner_id}"
            else:
                poll_winner = "РќРµ Р±СѓР»Рѕ РіРѕР»РѕСЃСѓРІР°РЅРЅСЏ"

        return {
            "films_count": films_count,
            "new_subs": new_subs,
            "top_user": top_user,
            "poll_winner": poll_winner,
        }

    # в”Ђв”Ђ Swipe & Joint Sessions в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def get_swipe_session(self, user_id: int):
        query = "SELECT * FROM swipe_sessions WHERE user_id = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_swipe_session(self, user_id: int, genres: str, last_tmdb_id: int, session_data: str):
        check_query = "SELECT id FROM swipe_sessions WHERE user_id = ?"
        db = await self._get_db()
        async with db.execute(check_query, (user_id,)) as cursor:
            exists = await cursor.fetchone()
            if exists:
                await db.execute(
                    "UPDATE swipe_sessions SET genres = ?, last_tmdb_id = ?, session_data = ? WHERE user_id = ?",
                    (genres, last_tmdb_id, session_data, user_id),
                )
            else:
                await db.execute(
                    "INSERT INTO swipe_sessions (user_id, genres, last_tmdb_id, session_data) VALUES (?, ?, ?, ?)",
                    (user_id, genres, last_tmdb_id, session_data),
                )
        await db.commit()

    async def create_watch_session(self, session_id: str, creator_id: int):
        query = "INSERT INTO watch_sessions (session_id, creator_id) VALUES (?, ?)"
        db = await self._get_db()
        await db.execute(query, (session_id, creator_id))
        await db.commit()

    async def get_watch_session(self, session_id: str):
        query = "SELECT * FROM watch_sessions WHERE session_id = ?"
        db = await self._get_db()
        async with db.execute(query, (session_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def add_session_vote(self, session_id: str, user_id: int, tmdb_id: int, vote: int):
        query = "INSERT INTO session_votes (session_id, user_id, tmdb_id, vote) VALUES (?, ?, ?, ?)"
        db = await self._get_db()
        await db.execute(query, (session_id, user_id, tmdb_id, vote))
        await db.commit()

    async def get_session_matches(self, session_id: str):
        query = """
        SELECT tmdb_id FROM session_votes
        WHERE session_id = ? AND vote = 1
        GROUP BY tmdb_id HAVING COUNT(DISTINCT user_id) >= 2
        """
        db = await self._get_db()
        async with db.execute(query, (session_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_session_voted_ids(self, session_id: str, user_id: int):
        query = "SELECT tmdb_id FROM session_votes WHERE session_id = ? AND user_id = ?"
        db = await self._get_db()
        async with db.execute(query, (session_id, user_id)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    # в”Ђв”Ђ Points & Games в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def add_points(self, user_id: int, points: int):
        query = "UPDATE users SET points = points + ? WHERE user_id = ?"
        await self._execute(query, (points, user_id))

    async def get_top_players(self, limit: int = 10):
        query = (
            "SELECT user_id, username, full_name, points "
            "FROM users ORDER BY points DESC LIMIT ?"
        )
        db = await self._get_db()
        async with db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_rating_guess(self, user_id: int, tmdb_id: int, guess: float, actual: float, points: int):
        query = """
        INSERT INTO rating_game (user_id, tmdb_id, guess_rating, actual_rating, points)
        VALUES (?, ?, ?, ?, ?)
        """
        await self._execute(query, (user_id, tmdb_id, guess, actual, points))

    # в”Ђв”Ђ Polls в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def create_poll(self, poll_id: str, movie_a_id: int, movie_b_id: int, ends_at):
        query = "INSERT INTO polls (poll_id, movie_a_id, movie_b_id, ends_at) VALUES (?, ?, ?, ?)"
        await self._execute(query, (poll_id, movie_a_id, movie_b_id, ends_at))

    async def add_poll_vote(self, poll_id: str, user_id: int, option: int):
        query = "INSERT INTO poll_votes (poll_id, user_id, option_voted) VALUES (?, ?, ?)"
        await self._execute(query, (poll_id, user_id, option))

    async def get_poll_vote_count(self, user_id: int):
        query = "SELECT COUNT(*) FROM poll_votes WHERE user_id = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # в”Ђв”Ђ Achievements в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

    async def save_achievement(self, user_id: int, ach_key: str):
        query = "INSERT OR IGNORE INTO achievements (user_id, achievement_key) VALUES (?, ?)"
        await self._execute(query, (user_id, ach_key))

    async def has_achievement(self, user_id: int, ach_key: str):
        query = "SELECT id FROM achievements WHERE user_id = ? AND achievement_key = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id, ach_key)) as cursor:
            row = await cursor.fetchone()
            return row is not None


# Р“Р»РѕР±Р°Р»СЊРЅРёР№ С–РЅСЃС‚Р°РЅСЃ
    # ── Middleware: ban check ──────────────────────────────────────────────

    async def is_banned(self, user_id: int) -> bool:
        """Returns True if user is banned."""
        row = await self.get_user(user_id)
        return bool(row and row.get("is_banned"))

    # ── Loyalty ranks ─────────────────────────────────────────────────────

    RANKS = [
        (7000, "👑 Легенда кіно"),
        (3000, "🏆 Синефіл"),
        (1500, "⭐ Критик"),
        (500,  "🍿 Кіноман"),
        (0,    "🎬 Кіноглядач"),
    ]

    def get_rank_for_points(self, points: int) -> str:
        for threshold, name in self.RANKS:
            if points >= threshold:
                return name
        return "🎬 Кіноглядач"

    async def get_user_rank(self, user_id: int) -> dict:
        """Returns current rank, points, next rank info."""
        user = await self.get_user(user_id)
        points = user.get("points", 0) if user else 0
        current_rank = self.get_rank_for_points(points)

        # Find next rank threshold
        next_rank = None
        next_threshold = None
        for threshold, name in reversed(self.RANKS):
            if threshold > points:
                next_rank = name
                next_threshold = threshold

        return {
            "rank": current_rank,
            "points": points,
            "next_rank": next_rank,
            "next_threshold": next_threshold,
            "points_to_next": (next_threshold - points) if next_threshold else 0,
        }

    # ── Top movies (community ratings) ───────────────────────────────────

    async def get_top_movies(self, period: str = "all", genre_filter: str = None, limit: int = 10) -> list:
        """
        Top movies by community average rating.
        period: 'week' | 'month' | 'all'
        """
        db = await self._get_db()
        params = []
        where_clauses = []

        if period == "week":
            where_clauses.append("r.created_at >= datetime('now', '-7 days')")
        elif period == "month":
            where_clauses.append("r.created_at >= datetime('now', '-30 days')")

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        query = f"""
        SELECT r.tmdb_id,
               ROUND(AVG(r.rating), 1) AS avg_rating,
               COUNT(r.id)             AS vote_count
        FROM ratings r
        {where_sql}
        GROUP BY r.tmdb_id
        HAVING COUNT(r.id) >= 3
        ORDER BY avg_rating DESC, vote_count DESC
        LIMIT ?
        """
        params.append(limit)
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ── Feedback ──────────────────────────────────────────────────────────

    async def save_feedback(self, user_id: int, fb_type: str, text: str) -> int:
        """Saves user feedback. Returns new row id."""
        query = """
        INSERT INTO feedback (user_id, type, text, status, created_at)
        VALUES (?, ?, ?, 'new', CURRENT_TIMESTAMP)
        """
        db = await self._get_db()
        async with db.execute(query, (user_id, fb_type, text)) as cursor:
            await db.commit()
            return cursor.lastrowid

    async def get_feedback_list(self, status: str = None, limit: int = 20) -> list:
        db = await self._get_db()
        if status:
            query = "SELECT * FROM feedback WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            async with db.execute(query, (status, limit)) as cursor:
                rows = await cursor.fetchall()
        else:
            query = "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?"
            async with db.execute(query, (limit,)) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_feedback_by_id(self, feedback_id: int) -> Optional[Dict[str, Any]]:
        db = await self._get_db()
        query = "SELECT * FROM feedback WHERE id = ?"
        async with db.execute(query, (feedback_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_feedback_status(self, feedback_id: int, status: str, admin_reply: str = None):
        db = await self._get_db()
        if admin_reply:
            await db.execute(
                "UPDATE feedback SET status = ?, admin_reply = ? WHERE id = ?",
                (status, admin_reply, feedback_id)
            )
        else:
            await db.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, feedback_id))
        await db.commit()

    # ── Saved quotes ──────────────────────────────────────────────────────

    async def save_quote(self, user_id: int, quote_text: str, film_name: str, tmdb_id: int = None) -> int:
        query = """
        INSERT INTO saved_quotes (user_id, quote_text, film_name, tmdb_id, saved_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """
        db = await self._get_db()
        async with db.execute(query, (user_id, quote_text, film_name, tmdb_id)) as cursor:
            await db.commit()
            return cursor.lastrowid

    async def get_saved_quotes(self, user_id: int, limit: int = 20) -> list:
        query = "SELECT * FROM saved_quotes WHERE user_id = ? ORDER BY saved_at DESC LIMIT ?"
        db = await self._get_db()
        async with db.execute(query, (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_saved_quote(self, user_id: int, quote_id: int):
        query = "DELETE FROM saved_quotes WHERE id = ? AND user_id = ?"
        await self._execute(query, (quote_id, user_id))

    async def get_saved_quotes_count(self, user_id: int) -> int:
        query = "SELECT COUNT(*) FROM saved_quotes WHERE user_id = ?"
        db = await self._get_db()
        async with db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # ── Admin: ban/unban, notes, log ──────────────────────────────────────

    async def ban_user(self, admin_id: int, user_id: int, reason: str = ""):
        db = await self._get_db()
        await db.execute(
            "UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?",
            (reason, user_id)
        )
        await db.execute(
            "INSERT INTO admin_log (admin_id, target_user_id, action, details) VALUES (?, ?, 'ban', ?)",
            (admin_id, user_id, reason)
        )
        await db.commit()

    async def unban_user(self, admin_id: int, user_id: int):
        db = await self._get_db()
        await db.execute(
            "UPDATE users SET is_banned = 0, ban_reason = NULL WHERE user_id = ?",
            (user_id,)
        )
        await db.execute(
            "INSERT INTO admin_log (admin_id, target_user_id, action, details) VALUES (?, ?, 'unban', '')",
            (admin_id, user_id)
        )
        await db.commit()

    async def set_admin_note(self, admin_id: int, user_id: int, note: str):
        db = await self._get_db()
        await db.execute("UPDATE users SET admin_note = ? WHERE user_id = ?", (note, user_id))
        await db.execute(
            "INSERT INTO admin_log (admin_id, target_user_id, action, details) VALUES (?, ?, 'note', ?)",
            (admin_id, user_id, note)
        )
        await db.commit()

    async def admin_add_points(self, admin_id: int, user_id: int, points: int, reason: str = ""):
        db = await self._get_db()
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.execute(
            "INSERT INTO admin_log (admin_id, target_user_id, action, details) VALUES (?, ?, 'add_points', ?)",
            (admin_id, user_id, f"+{points} | {reason}")
        )
        await db.commit()

    async def get_admin_log(self, limit: int = 50) -> list:
        query = "SELECT * FROM admin_log ORDER BY created_at DESC LIMIT ?"
        db = await self._get_db()
        async with db.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def search_users(self, query_str: str, limit: int = 10) -> list:
        """Search users by username or user_id (sanitizes LIKE)."""
        db = await self._get_db()
        query_clean = query_str.strip()
        # Try numeric first (user_id search)
        if query_clean.isdigit():
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ? LIMIT ?",
                (int(query_clean), limit)
            ) as cursor:
                rows = await cursor.fetchall()
                if rows:
                    return [dict(row) for row in rows]
        # Username search with sanitization for LIKE
        username_query = query_clean.lstrip('@')
        # Escape special LIKE characters: % and _
        sanitized = username_query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        async with db.execute(
            "SELECT * FROM users WHERE username LIKE ? ESCAPE '\\' LIMIT ?",
            (f"%{sanitized}%", limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]



# Глобальний інстанс
from src.config import config
db = Database(config.DB_PATH)