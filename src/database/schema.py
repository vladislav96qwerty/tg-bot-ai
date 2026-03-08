CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    language_code TEXT,
    is_sponsor INTEGER DEFAULT 0,
    channel_member_checked_at TIMESTAMP,
    daily_rec_enabled INTEGER DEFAULT 1,
    is_banned INTEGER DEFAULT 0,
    ban_reason TEXT,
    admin_note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_USER_PREFERENCES_TABLE = """
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    genres TEXT, -- comma-separated
    view_frequency TEXT,
    fav_period TEXT,
    ai_taste_profile TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

CREATE_WATCHLIST_TABLE = """
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tmdb_id INTEGER,
    title_ua TEXT,
    status TEXT DEFAULT 'want', -- want, watching, watched
    category TEXT,
    poster_path TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

CREATE_RATINGS_TABLE = """
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tmdb_id INTEGER,
    rating INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

CREATE_CHANNEL_POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS channel_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    post_type TEXT, -- morning, controversial, hidden_gem, etc.
    preview_text TEXT,
    tmdb_id INTEGER,
    content TEXT,
    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ACHIEVEMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    achievement_key TEXT,
    earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

CREATE_SWIPE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS swipe_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    genres TEXT,
    last_tmdb_id INTEGER,
    session_data TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

CREATE_WATCH_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS watch_sessions (
    session_id TEXT PRIMARY KEY,
    creator_id INTEGER,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_SESSION_VOTES_TABLE = """
CREATE TABLE IF NOT EXISTS session_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id INTEGER,
    tmdb_id INTEGER,
    vote INTEGER, -- 1 for like, 0 for dislike
    FOREIGN KEY (session_id) REFERENCES watch_sessions (session_id)
);
"""

CREATE_POLLS_TABLE = """
CREATE TABLE IF NOT EXISTS polls (
    poll_id TEXT PRIMARY KEY,
    movie_a_id INTEGER,
    movie_b_id INTEGER,
    ends_at TIMESTAMP
);
"""

CREATE_POLL_VOTES_TABLE = """
CREATE TABLE IF NOT EXISTS poll_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id TEXT,
    user_id INTEGER,
    option_voted INTEGER,
    FOREIGN KEY (poll_id) REFERENCES polls (poll_id)
);
"""

CREATE_RATING_GAME_TABLE = """
CREATE TABLE IF NOT EXISTS rating_game (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tmdb_id INTEGER,
    guess_rating REAL,
    actual_rating REAL,
    points INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

CREATE_REFERRALS_TABLE = """
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER,
    referred_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (referrer_id) REFERENCES users (user_id),
    FOREIGN KEY (referred_id) REFERENCES users (user_id)
);
"""

# ── НОВА: Скринька зворотного зв'язку ─────────────────────────────────────
CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,          -- bug / suggestion / other
    text TEXT,
    status TEXT DEFAULT 'new',   -- new / reviewed / done
    admin_reply TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

# ── НОВА: Збережені цитати ─────────────────────────────────────────────────
CREATE_SAVED_QUOTES_TABLE = """
CREATE TABLE IF NOT EXISTS saved_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    quote_text TEXT,
    film_name TEXT,
    tmdb_id INTEGER,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

# ── НОВА: Лог дій адміна ───────────────────────────────────────────────────
CREATE_ADMIN_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    target_user_id INTEGER,
    action TEXT,         -- ban / unban / add_points / message / note
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

ALL_TABLES = [
    CREATE_USERS_TABLE,
    CREATE_USER_PREFERENCES_TABLE,
    CREATE_WATCHLIST_TABLE,
    CREATE_RATINGS_TABLE,
    CREATE_CHANNEL_POSTS_TABLE,
    CREATE_ACHIEVEMENTS_TABLE,
    CREATE_SWIPE_SESSIONS_TABLE,
    CREATE_WATCH_SESSIONS_TABLE,
    CREATE_SESSION_VOTES_TABLE,
    CREATE_POLLS_TABLE,
    CREATE_POLL_VOTES_TABLE,
    CREATE_RATING_GAME_TABLE,
    CREATE_REFERRALS_TABLE,
    CREATE_FEEDBACK_TABLE,       # ← НОВА
    CREATE_SAVED_QUOTES_TABLE,   # ← НОВА
    CREATE_ADMIN_LOG_TABLE,      # ← НОВА
]