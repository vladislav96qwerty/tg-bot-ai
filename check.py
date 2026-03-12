"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        NeNetflixBot — ULTIMATE STATIC CHECKER v8                           ║
║  Запускати з кореня проекту:  python check.py                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  БЛОК A — СТАТИЧНИЙ АНАЛІЗ КОДУ (A01-A50)                                  ║
║  БЛОК B — СИМУЛЯЦІЯ КОРИСТУВАЧА (кожна кнопка, включно v2.0)               ║
║  БЛОК C — СИМУЛЯЦІЯ АДМІНА (включно User Management v2.0)                  ║
║  БЛОК D — MIDDLEWARE                                                        ║
║  БЛОК E — ПЕРЕВІРКА .env ФАЙЛУ                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import re
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple

# ─── ANSI ────────────────────────────────────────────────────────────────────
R  = "\033[0m"
G  = "\033[92m"
RE = "\033[91m"
Y  = "\033[93m"
C  = "\033[96m"
B  = "\033[94m"
BO = "\033[1m"
DM = "\033[2m"

issues   = 0
warnings = 0
passed   = 0

def ok(m):
    global passed; passed += 1
    print(f"  {G}OK  {m}{R}")

def err(m):
    global issues; issues += 1
    print(f"  {RE}ERR {m}{R}")

def warn(m):
    global warnings; warnings += 1
    print(f"  {Y}WRN {m}{R}")

def info(m):
    print(f"  {C}INF {m}{R}")

def hdr(m):
    print(f"\n{BO}{C}{'─'*72}\n  {m}\n{'─'*72}{R}")

def sub(m):
    print(f"\n  {BO}{m}{R}")

# ─── LOAD FILES ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
def strip_comments(code: str) -> str:
    """
    Removes Python comments for static analysis
    """
    return re.sub(r'#.*', '', code)

def load() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if any(x in rel for x in ["venv", "__pycache__", "check.py", ".git"]):
            continue
        try:
            out[rel] = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            out[rel] = ""
    return out

FILES = load()

def src(name: str) -> str:
    return FILES.get(name, "")

# ─── KNOWN LAYOUT ─────────────────────────────────────────────────────────────
ROUTERS = [
    "src/routers/common.py",
    "src/routers/movie.py",
    "src/routers/onboarding.py",
    "src/routers/daily_picks.py",
    "src/routers/recommendations.py",
    "src/routers/watchlist.py",
    "src/routers/profile.py",
    "src/routers/referrals.py",
    "src/routers/swipe.py",
    "src/routers/joint_watch.py",
    "src/routers/games.py",
    "src/routers/admin_tools.py",
    "src/routers/menu_handlers.py",
]

CRITICAL = [
    "main.py", "src/config.py",
    "src/database/db.py", "src/database/schema.py",
    "src/middlewares/subscription.py",
    "src/services/ai.py", "src/services/tmdb.py",
    "src/services/scheduler.py", "src/services/prompts.py",
    "src/services/recommender.py",
    "src/keyboards/main_menu.py",
] + ROUTERS

# ─── HANDLER INDEX ────────────────────────────────────────────────────────────
def build_handler_index() -> Tuple[Set[str], Set[str], Set[str]]:
    exact: Set[str] = set()
    prefix: Set[str] = set()
    cmds: Set[str] = set()
    for s in FILES.values():
        s = strip_comments(s)
        exact.update(re.findall(r'F\.data\s*==\s*["\']([^"\']+)["\']', s))
        prefix.update(re.findall(r'F\.data\.startswith\(["\']([^"\']+)["\']\)', s))
        cmds.update(re.findall(r'Command\(["\'](\w+)["\']', s))
    return exact, prefix, cmds

EXACT, PREFIX, CMDS = build_handler_index()

def is_handled(cb: str) -> Tuple[bool, str]:
    if cb in EXACT:
        return True, "exact"
    for p in PREFIX:
        if cb.startswith(p):
            return True, f"prefix '{p}'"
    return False, ""


# ══════════════════════════════════════════════════════════════════════════════
#  БЛОК A
# ══════════════════════════════════════════════════════════════════════════════

def a01_file_existence():
    hdr("A01 - НАЯВНIСТЬ ФАЙЛIВ НА ДИСКУ")
    for f in CRITICAL:
        if src(f):
            ok(f)
        else:
            err(f"{f}  -- ФАЙЛ НЕ ЗНАЙДЕНО")


def a02_imports():
    hdr("A02 - IМПОРТИ")
    NEED = {
        "main.py": [
            "aiogram", "src.config", "src.routers", "src.database.db",
            "src.middlewares.subscription", "src.services.scheduler"
        ],
        "src/config.py": ["dotenv", "os"],
        "src/database/db.py": ["libsql_client", "src.database.schema"],
        "src/services/ai.py": ["groq", "google", "src.config"],
        "src/services/tmdb.py": ["aiohttp", "src.config"],
        "src/services/scheduler.py": [
            "apscheduler", "src.services.ai", "src.services.tmdb",
            "src.services.prompts"
        ],
        "src/services/recommender.py": [
            "src.database.db", "src.services.ai", "src.services.tmdb",
            "src.services.prompts"
        ],
        "src/routers/recommendations.py": ["src.services.recommender"],
    }
    for fname, need in NEED.items():
        s = src(fname)
        if not s:
            continue
        miss = [x for x in need if x not in s]
        if miss:
            err(f"{fname}: вiдсутнi iмпорти -> {miss}")
        else:
            ok(f"{fname}: iмпорти OK")


def a03_duplicate_handlers():
    hdr("A03 - ДУБЛIКАТИ CALLBACK-ХЕНДЛЕРIВ")
    seen: Dict[str, List[str]] = defaultdict(list)
    for fpath, s in FILES.items():
        s = strip_comments(s)
        for cb in re.findall(r'F\.data\s*==\s*["\']([^"\']+)["\']', s):
            seen[cb].append(fpath)
    found = False
    for cb, files in sorted(seen.items()):
        uniq = list(dict.fromkeys(files))
        if len(uniq) > 1:
            found = True
            err(f"ДУБЛIКАТ '{cb}' у: {[f.split('/')[-1] for f in uniq]}")
    if not found:
        ok("Дублiкатiв не знайдено")


def a04_db_methods():
    hdr("A04 - DB МЕТОДИ -- ВИКЛИКИ vs ВИЗНАЧЕННЯ")
    db_s = src("src/database/db.py")
    defined: Set[str] = set(re.findall(r'^\s{4}(?:async )?def (\w+)\(', db_s, re.M))

    # Методи, які ми ігноруємо при перевірці на "невикористання" (A04)
    INTERNAL = {"_execute", "_add_column_if_missing", "_get_db", "__init__", "execute", "fetchone", "fetchall", "commit", "keys", "__aenter__", "__aexit__", "__await__", "__getitem__", "__iter__", "__len__"}

    callers: Dict[str, List[str]] = defaultdict(list)
    for fpath, s in FILES.items():
        s = strip_comments(s)
        if fpath == "src/database/db.py":
            continue
        for c in re.findall(r'(?:await\s+)?db\.([a-z]\w+)\(', s):
            callers[c].append(fpath.split("/")[-1])

    for m in sorted(callers):
        if m not in defined:
            err(f"db.{m}() -- НЕ ВИЗНАЧЕНО  <- {set(callers[m])}")
        else:
            ok(f"db.{m}()")

    for m in sorted(defined - set(callers) - INTERNAL):
        warn(f"db.{m}() -- визначено, але нiколи не викликається")


def a05_tmdb_methods():
    hdr("A05 - TMDB МЕТОДИ -- ВИКЛИКИ vs ВИЗНАЧЕННЯ")
    ts = src("src/services/tmdb.py")
    defined: Set[str] = set(re.findall(r'(?:async )?def (\w+)\(', ts))

    INTERNAL = {"__init__", "_get", "_get_session"}

    calls: Dict[str, Set[str]] = defaultdict(set)
    for fpath, s in FILES.items():
        if fpath == "src/services/tmdb.py":
            continue
        for c in re.findall(r'tmdb_service\.(\w+)\(', s):
            calls[c].add(fpath.split("/")[-1])

    for m in sorted(calls):
        if m not in defined:
            err(f"tmdb_service.{m}() -- НЕ ВИЗНАЧЕНО  <- {calls[m]}")
        else:
            ok(f"tmdb_service.{m}()")

    for m in sorted(defined - set(calls) - INTERNAL):
        warn(f"tmdb_service.{m}() -- визначено, нiколи не викликається")


def a06_ai_null_checks():
    hdr("A06 - ai_service.ask() -- ПЕРЕВIРКА NULL-РЕЗУЛЬТАТУ")
    for fpath, s in FILES.items():
        if fpath == "src/services/ai.py":
            continue
        for m in re.finditer(r'(\w+)\s*=\s*await\s+ai_service\.ask\(', s):
            v = m.group(1)
            window = s[m.start(): m.start() + 600]
            pat = rf'if\s+(not\s+)?{re.escape(v)}[\s\n\[:]'
            if re.search(pat, window):
                ok(f"{fpath.split('/')[-1]}: '{v}' перевiрено на None")
            else:
                warn(f"{fpath.split('/')[-1]}: '{v}' без перевiрки -- crash якщо AI впаде")


def a07_schema():
    hdr("A07 - СХЕМА БД -- ТАБЛИЦI, КОЛОНКИ, МIГРАЦII")
    sc = src("src/database/schema.py")
    tables: Dict[str, Set[str]] = {}
    for m in re.finditer(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);', sc, re.DOTALL):
        tname, body = m.group(1), m.group(2)
        cols = set(re.findall(r'^\s+(\w+)\s+\w', body, re.M))
        cols -= {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}
        tables[tname] = cols
    ok(f"Таблицi ({len(tables)}): {sorted(tables)}")

    db_s = src("src/database/db.py")
    for tname, col in re.findall(
        r'_add_column_if_missing\(db,\s*["\'](\w+)["\'],\s*["\'](\w+)["\']', db_s
    ):
        if tname in tables:
            ok(f"Мiграцiя: {tname}.{col}")
        else:
            err(f"Мiграцiя на невiдому таблицю '{tname}'")

    if "ALL_TABLES" in sc:
        for t in tables:
            if t in sc:
                ok(f"ALL_TABLES мiстить {t}")
            else:
                err(f"ALL_TABLES не мiстить {t}")


def a08_config():
    hdr("A08 - CONFIG ЗМIННI")
    cfg = src("src/config.py")
    defined = re.findall(r'^\s{4}([A-Z_]+)\s*=', cfg, re.M)
    ok(f"Визначено {len(defined)}: {defined}")

    used: Dict[str, List[str]] = defaultdict(list)
    for fpath, s in FILES.items():
        if fpath == "src/config.py":
            continue
        for v in re.findall(r'config\.([A-Z_]+)', s):
            used[v].append(fpath.split("/")[-1])

    for v in sorted(used):
        if v not in defined:
            err(f"config.{v} -- НЕ ВИЗНАЧЕНО  <- {set(used[v])}")
        else:
            ok(f"config.{v}")

    vblock = re.search(r'def validate\(self\)(.*?)(?=\n    def |\Z)', cfg, re.DOTALL)
    if vblock:
        validated = set(re.findall(r'"([A-Z_]+)"', vblock.group(1)))
        for key in ["BOT_TOKEN", "CHANNEL_ID", "GROQ_API_KEY", "TMDB_API_KEY", "GEMINI_API_KEY"]:
            if key in validated:
                ok(f"validate() перевiряє {key}")
            else:
                err(f"validate() не перевiряє {key} -- тихий крах при вiдсутностi")
    else:
        err("validate() вiдсутнiй в Config")

    if re.search(r'CHANNEL_ID\s*=\s*int\(', cfg):
        ok("CHANNEL_ID -- int")
    elif 'CHANNEL_ID' in cfg:
        warn("CHANNEL_ID зберiгається як str -- get_chat_member() може падати")


def a09_prompts():
    hdr("A09 - AI ПРОМПТИ -- ВИЗНАЧЕННЯ, ВИКОРИСТАННЯ, ПЛЕЙСХОЛДЕРИ")
    ps = src("src/services/prompts.py")
    defined = re.findall(r'^([A-Z_]+_PROMPT)\s*=\s*"""', ps, re.M)
    if not defined:
        err("Промптiв не знайдено")
        return
    ok(f"Визначено ({len(defined)}): {defined}")

    used: Dict[str, List[str]] = defaultdict(list)
    for fpath, s in FILES.items():
        if fpath == "src/services/prompts.py":
            continue
        for p in re.findall(r'\b([A-Z_]+_PROMPT)\b', s):
            used[p].append(fpath.split("/")[-1])

    for p in defined:
        if p not in used:
            warn(f"{p} -- визначено, але не використовується")
        else:
            ok(f"{p} <- {set(used[p])}")
    for p in sorted(used):
        if p not in defined:
            err(f"{p} -- використовується але НЕ ВИЗНАЧЕНО")

    sub("Плейсхолдери .format()")
    for prompt in defined:
        m = re.search(rf'{prompt}\s*=\s*"""(.*?)"""', ps, re.DOTALL)
        if not m:
            continue
        pholders = re.findall(r'(?<!\{)\{([a-zA-Z_]\w*)\}(?!\})', m.group(1))
        for fpath, s in FILES.items():
            for cm in re.finditer(rf'\b{prompt}\.format\(', s):
                start = cm.end()
                depth = 1
                end = start
                while end < len(s) and depth:
                    if s[end] == '(':
                        depth += 1
                    elif s[end] == ')':
                        depth -= 1
                    end += 1
                provided = re.findall(r'(\w+)\s*=', s[start:end - 1])
                miss = [ph for ph in pholders if ph not in provided]
                fname = fpath.split("/")[-1]
                if miss:
                    err(f"{prompt} у {fname}: вiдсутнi плейсхолдери -> {miss}")
                else:
                    ok(f"{prompt} у {fname}: плейсхолдери OK")


def a10_fsm():
    hdr("A10 - FSM СТАНИ -- ПЕРЕХОДИ, CLEAR")
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        groups = re.findall(r'class (\w+)\(StatesGroup\)', s)
        if not groups:
            continue
        sub(name)
        for g in groups:
            m = re.search(rf'class {g}\(StatesGroup\)(.*?)(?=\nclass |\Z)', s, re.DOTALL)
            if not m:
                continue
            states = [f"{g}.{x}" for x in re.findall(r'(\w+)\s*=\s*State\(\)', m.group(1))]
            set_calls = re.findall(r'set_state\((\w+\.\w+)\)', s)
            clears = len(re.findall(r'state\.clear\(\)', s))
            print(f"    Стани: {states}")
            never_set = [x for x in states if x not in set_calls]
            if never_set:
                warn(f"{g}: нiколи не встановлюється: {never_set}")
            else:
                ok(f"{g}: всi стани досяжнi")
            if clears:
                ok(f"{g}: state.clear() викликається {clears} раз(и)")
            else:
                warn(f"{g}: немає state.clear() -- FSM може зависнути мiж сесiями")


def a11_router_order():
    hdr("A11 - ПОРЯДОК РЕЄСТРАЦII РОУТЕРIВ")
    ms = src("main.py")
    registered = re.findall(r'dp\.include_router\((\w+)\.router\)', ms)
    names = [r.split("/")[-1].replace(".py", "") for r in ROUTERS]
    for n in names:
        if n in registered:
            ok(f"{n} зареєстровано")
        else:
            err(f"{n} -- НЕ зареєстровано в main.py!")

    if "admin_tools" in registered and "movie" in registered:
        ai_idx = registered.index("admin_tools")
        mi_idx = registered.index("movie")
        if ai_idx < mi_idx:
            ok("admin_tools перед movie -- FSM не перехоплюється text_search")
        else:
            err("admin_tools пiсля movie -> UserSearchStates йде до text_search!")

    if registered and registered[0] == "common":
        ok("common -- перший роутер")
    else:
        warn(f"common не перший (є: {registered[0] if registered else 'none'})")

    if registered and registered[-1] == "menu_handlers":
        ok("menu_handlers -- останнiй")
    else:
        warn("menu_handlers не останнiй -- може shadowити хендлери")


def a12_callback_length():
    hdr("A12 - callback_data <= 64 БАЙТИ (TELEGRAM LIMIT)")
    found = False
    for fpath, s in FILES.items():
        for cb in re.findall(r'callback_data\s*=\s*["\']([^"\']+)["\']', s):
            if len(cb.encode()) > 64:
                found = True
                err(f"'{cb}' = {len(cb.encode())} байт > 64  ({fpath.split('/')[-1]})")
    if not found:
        ok("Всi статичнi callback_data в межах 64 байт")


def a13_markdown_bold():
    hdr("A13 - MARKDOWN v1: **bold** ЗАМIСТЬ *bold*")
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        if 'parse_mode="Markdown"' not in s and "parse_mode='Markdown'" not in s:
            continue
        bolds = re.findall(r'\*\*[^*\n]{1,80}\*\*', s)
        if bolds:
            err(f"{name}: знайдено **bold** у Markdown v1 -- буде вiдображено як **текст**!")
            for b in bolds[:4]:
                print(f"    {RE}-> {b!r}{R}")
        else:
            ok(f"{name}: **bold** не виявлено")


def a14_parse_mode_mix():
    hdr("A14 - ЗМIШАНI parse_mode В ОДНОМУ ФАЙЛI")
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        modes = []
        if 'parse_mode="Markdown"' in s or "parse_mode='Markdown'" in s:
            modes.append("Markdown")
        if 'parse_mode="MarkdownV2"' in s:
            modes.append("MarkdownV2")
        if 'parse_mode="HTML"' in s:
            modes.append("HTML")
        if len(modes) > 1:
            warn(f"{name}: змiшанi режими -> {modes} -- легко отримати ParseError")
        elif modes:
            ok(f"{name}: {modes[0]}")
        else:
            info(f"{name}: plain text")


def a15_stale_keyboard():
    hdr("A15 - STALE KEYBOARD: reply_markup=callback.message.reply_markup")
    found = False
    for fpath, s in FILES.items():
        for m in re.finditer(r'reply_markup\s*=\s*callback\.message\.reply_markup', s):
            found = True
            ln = s[:m.start()].count('\n') + 1
            err(f"{fpath.split('/')[-1]}:{ln} -- стара клавiатура reuse, кнопки можуть бути застарiлими")
    if not found:
        ok("Stale keyboard reuse не виявлено")


def a16_html_injection():
    hdr("A16 - HTML-IN'ЄКЦIЯ: данi користувача без html.escape()")
    risky = ["full_name", "username", "title", "first_name"]
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        if 'parse_mode="HTML"' not in s:
            continue
        for field in risky:
            for m in re.finditer(rf'f["\'][^"\']*\{{{re.escape(field)}}}', s):
                ctx = s[max(0, m.start() - 200): m.start() + 200]
                if "html.escape" not in ctx and 'parse_mode="HTML"' in ctx:
                    ln = s[:m.start()].count('\n') + 1
                    warn(f"{name}:{ln} можлива HTML-iн'єкцiя з '{field}' без html.escape()")


def a17_bare_except():
    hdr("A17 - BARE except: (ЛОВИть ВСЕ включно SystemExit)")
    found = False
    for fpath, s in FILES.items():
        for m in re.finditer(r'except\s*:\s', s):
            found = True
            ln = s[:m.start()].count('\n') + 1
            warn(f"{fpath.split('/')[-1]}:{ln} -- bare except: замiсть except Exception:")
    if not found:
        ok("Bare except не знайдено")


def a18_api_no_try():
    hdr("A18 - ЗОВНIШНI API-ВИКЛИКИ БЕЗ try/except")
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        for m in re.finditer(
            r'async def (\w+)\([^)]*(?:callback|message)[^)]*\):(.*?)(?=\nasync def |\Z)',
            s, re.DOTALL
        ):
            fname_, body = m.group(1), m.group(2)
            has_api = bool(
                re.search(r'await\s+(?:tmdb_service|ai_service|callback\.bot|bot\.)', body)
            )
            has_try = 'try:' in body
            if has_api and not has_try:
                warn(f"{name}.{fname_}: зовнiшнiй API-виклик без try/except")


def a19_hardcoded_secrets():
    hdr("A19 - HARDCODED ТОКЕНИ/КЛЮЧI В КОДІ")
    patterns = [
        (r'\b\d{8,12}:[A-Za-z0-9_-]{35}\b', "Telegram bot token"),
        (r'\bgsk_[A-Za-z0-9]{50,}\b', "Groq API key"),
        (r'\bAIza[A-Za-z0-9_-]{35}\b', "Google API key"),
    ]
    found = False
    for fpath, s in FILES.items():
        if ".env" in fpath:
            continue
        for pat, label in patterns:
            hits = re.findall(pat, s)
            if hits:
                found = True
                err(f"HARDCODED {label} у {fpath.split('/')[-1]}: {hits[0][:20]}...")
    if not found:
        ok("Hardcoded секретiв не знайдено")


def a20_n_plus_one():
    hdr("A20 - N+1 ЗАПИТ: get_all() -> find one")
    found = False
    for fpath, s in FILES.items():
        lines = s.split('\n')
        for i, line in enumerate(lines):
            m = re.search(r'(\w+)\s*=\s*await db\.get_\w+\(', line)
            if not m:
                continue
            v = m.group(1)
            for j in range(i + 1, min(i + 6, len(lines))):
                stripped = lines[j].strip()
                if stripped.startswith(f"if {v}") or stripped.startswith(f"if not {v}"):
                    break
                if re.search(rf'\bnext\([^)]*for\s+\w+\s+in\s+{re.escape(v)}\b', stripped):
                    found = True
                    warn(f"{fpath.split('/')[-1]}:{j+1} -- завантажено весь список щоб знайти 1 елемент")
                    break
    if not found:
        ok("N+1 паттернiв не виявлено")


def a21_json_text_collision():
    hdr("A21 - JSON vs TEXT КОЛIЗIЯ В channel_posts (daily_picks)")
    dp = src("src/routers/daily_picks.py")
    sch = src("src/services/scheduler.py")
    db_s = src("src/database/db.py")
    sched_saves_text = "save_channel_post" in sch
    router_reads_json = "json.loads" in dp and "get_recent_daily_picks" in dp
    if sched_saves_text and router_reads_json:
        if "daily_picks_cache" in db_s:
            ok("Окремий тип 'daily_picks_cache' -- колiзiя усунена")
        elif re.search(r'try:.*json\.loads', dp, re.DOTALL):
            ok("json.loads у try/except -- колiзiя обробляється")
        else:
            err("Scheduler зберiгає TEXT, роутер робить json.loads -> JSONDecodeError при кешованому постi")
    else:
        ok("JSON/TEXT колiзii не виявлено")


def a22_channel_id_type():
    hdr("A22 - CHANNEL_ID ТИП")
    cfg = src("src/config.py")
    if re.search(r'CHANNEL_ID\s*=\s*int\(', cfg):
        ok("CHANNEL_ID -- int")
    elif 'CHANNEL_ID' in cfg:
        warn("CHANNEL_ID зберiгається як str -- get_chat_member(chat_id=str) може дати помилку")


def a23_admin_filter():
    hdr("A23 - ADMIN FILTER НА ВСIХ adm_* ХЕНДЛЕРАХ")
    as_ = src("src/routers/admin_tools.py")
    for m in re.finditer(
        r'@router\.callback_query\(F\.data\s*==\s*["\']admin_[^"\']+["\']([^)]*)\)', as_
    ):
        ctx = m.group(1)
        btn_match = re.search(r'"admin_[^"]+"', m.group(0))
        btn = btn_match.group(0) if btn_match else "?"
        if "admin_filter" in ctx:
            ok(f"{btn} -> admin_filter")
        else:
            err(f"{btn} -> НЕ МАЄ admin_filter -- будь-хто може викликати!")

    for m in re.finditer(
        r'@router\.callback_query\(F\.data\.startswith\(["\']adm_set["\']([^)]*)\)', as_
    ):
        ctx = m.group(1)
        if "admin_filter" in ctx:
            ok("adm_set: prefix -> admin_filter")
        else:
            err("adm_set: хендлер БЕЗ admin_filter -- будь-хто може видати спонсора!")


def a24_broadcast_guard():
    hdr("A24 - confirm_broadcast -- FSM STATE + ADMIN FILTER")
    as_ = src("src/routers/admin_tools.py")
    m = re.search(
        r'@router\.callback_query\(F\.data\s*==\s*["\']confirm_broadcast["\']([^)]*)\)', as_
    )
    if not m:
        warn("confirm_broadcast хендлер не знайдено")
        return
    ctx = m.group(1)
    has_state = "BroadcastStates" in ctx
    has_filter = "admin_filter" in ctx
    if has_state and has_filter:
        ok("confirm_broadcast: FSM state + admin_filter")
    else:
        if not has_state:
            err("confirm_broadcast: немає FSM state -> replay attack можливий")
        if not has_filter:
            err("confirm_broadcast: немає admin_filter -> будь-хто запустить розсилку!")


def a25_recommender():
    hdr("A25 - recommender.py IСНУЄ")
    s = src("src/services/recommender.py")
    if s:
        if "recommender_service" in s:
            ok("recommender.py iснує i мiстить recommender_service")
        else:
            err("recommender.py iснує але recommender_service не визначено")
    else:
        err("src/services/recommender.py НЕ ЗНАЙДЕНО -- ImportError при запуску!")


def a26_scheduler():
    hdr("A26 - SCHEDULER -- JOBS, TIMEZONE, TRY/EXCEPT, START()")
    ss = src("src/services/scheduler.py")
    ms = src("main.py")
    jobs = re.findall(
        r'scheduler\.add_job\((self\.\w+),\s*"cron"[^)]+hour=(\d+)[^)]+minute=(\d+)', ss
    )
    ok(f"Jobs зареєстровано: {len(jobs)}")
    for method, h, m_ in jobs:
        print(f"    {DM}* {method}  ->  {h.zfill(2)}:{m_.zfill(2)} Kyiv{R}")

    tz = re.search(r'timezone\s*=\s*["\']([^"\']+)["\']', ss)
    if tz:
        ok(f"Timezone: {tz.group(1)}")
    else:
        warn("Timezone не вказано -- використовується UTC")

    if ".start()" in ms and "ChannelScheduler" in ms:
        ok("scheduler.start() викликається в main.py")
    else:
        err("scheduler.start() НЕ ЗНАЙДЕНО в main.py -- tasks не запустяться!")

    for method, _, _ in jobs:
        mn = method.replace("self.", "")
        m = re.search(rf'async def {mn}\(self\)(.*?)(?=\n    async def |\Z)', ss, re.DOTALL)
        if m:
            if 'try:' in m.group(1) and 'except' in m.group(1):
                ok(f"{mn}: try/except")
            else:
                warn(f"{mn}: немає try/except -- виняток вб'є job назавжди")


def a27_deeplinks():
    hdr("A27 - DEEP-LINK ПАРАМЕТРИ (/start ref_ та joint_)")
    cs = src("src/routers/common.py")
    checks = [
        ("ref_ обробляється в /start", "ref_" in cs),
        ("joint_ обробляється в /start", "joint_" in cs),
        ("ValueError/IndexError ловиться", "ValueError" in cs or "IndexError" in cs),
        ("Захист вiд само-реферала", "referrer_id != user_id" in cs),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)


def a28_none_guards():
    hdr("A28 - NULL-GUARD ПIСЛЯ db.get_X() ПЕРЕД ВИКОРИСТАННЯМ")
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        lines = s.split('\n')
        for i, line in enumerate(lines):
            m = re.search(r'(\w+)\s*=\s*await db\.get_\w+\(', line)
            if not m:
                continue
            v = m.group(1)
            guarded = False
            for j in range(i + 1, min(i + 5, len(lines))):
                t = lines[j].strip()
                if re.match(rf'if\s+(not\s+)?{re.escape(v)}[\s:\[]', t):
                    guarded = True
                    break
                if re.search(rf'\b{re.escape(v)}\s*[\.\[]', t) and not guarded:
                    warn(f"{name}:{j+1} '{v}' використовується без None-перевiрки")
                    break
def a29_blocking_calls():
    hdr("A29 - BLOCKING CALLS В ASYNC КОДI")

    patterns = [
        ("requests.", "requests library"),
        ("time.sleep(", "time.sleep"),
        ("subprocess.run(", "subprocess.run"),
    ]

    found = False

    for fpath, s in FILES.items():
        s = strip_comments(s)

        for p, label in patterns:
            if p in s:
                found = True
                warn(f"{fpath.split('/')[-1]} використовує {label} -- блокує event loop")

    if not found:
        ok("Blocking calls не знайдено")

def a30_missing_await():
    hdr("A30 - МОЖЛИВИЙ MISSING AWAIT")
    # Рядковий підхід: шукаємо виклики сервісів без await на тому ж рядку
    SERVICES = ("db.", "tmdb_service.", "ai_service.")
    SYNC_OK  = ("get_poster_url", "build_justwatch_url", "PROVIDER_MAP",
                "BLACKLISTED_PROVIDERS", "IMAGE_BASE_URL", "BASE_URL", "api_key", ".get(", ".keys(", ".pop(")
    found = False
    for fpath, s in FILES.items():
        s_clean = strip_comments(s)
        for lineno, line in enumerate(s_clean.split('\n'), 1):
            st = line.strip()
            if not st or st.startswith(('#', '"', "'")):
                continue
            if st.startswith(('async with', 'async def', 'def ', 'class ')):
                continue
            for svc in SERVICES:
                if svc not in st:
                    continue
                if any(m in st for m in SYNC_OK):
                    continue
                if 'await' not in st and '=' not in st.split(svc)[0].strip():
                    # відфільтровуємо присвоєння self.tmdb_service = ...
                    if not re.match(r'(self\.)?\w+\s*=\s*', st.split(svc)[0]):
                        warn(f"{fpath.split('/')[-1]}:{lineno} можливий missing await -> {st[:70]}")
                        found = True
                        break
    if not found:
        ok("Missing await не знайдено")

def a31_prefix_collisions():
    hdr("A31 - PREFIX COLLISION (startswith handlers)")

    collisions = []

    for p1 in PREFIX:
        for p2 in PREFIX:
            if p1 != p2 and p2.startswith(p1):
                collisions.append((p1, p2))

    if collisions:
        for a, b in collisions:
            warn(f"Prefix '{a}' може перехоплювати '{b}'")
    else:
        ok("Prefix collision не знайдено")


def a32_watch_providers():
    hdr("A32 - WATCH PROVIDERS (кнопки JustWatch у постах)")
    tmdb_s = src("src/services/tmdb.py")
    sched_s = src("src/services/scheduler.py")
    mh_s    = src("src/routers/menu_handlers.py")
    mv_s    = src("src/routers/movie.py")

    checks = [
        ("tmdb.py: get_watch_providers() визначено",
            bool(re.search(r'def get_watch_providers', tmdb_s))),
        ("tmdb.py: /watch/providers endpoint",
            "/watch/providers" in tmdb_s),
        ("tmdb.py: fallback region (PL або EN)",
            bool(re.search(r'region.*["\']PL["\']|region.*["\']EN["\']', tmdb_s))),
        ("scheduler.py: _build_watch_keyboard або get_watch_providers",
            "_build_watch_keyboard" in sched_s or "get_watch_providers" in sched_s),
        ("scheduler.py: JustWatch fallback кнопка",
            "justwatch.com" in sched_s),
        ("movie.py або menu_handlers.py: JustWatch кнопка у картці",
            "justwatch.com" in mv_s or "justwatch.com" in mh_s),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)


def a33_saved_quotes():
    hdr("A33 - SAVED QUOTES -- md5-ключ, збереження, видалення")
    sc = src("src/database/schema.py")
    db_s = src("src/database/db.py")
    sched_s = src("src/services/scheduler.py")
    mh_s = src("src/routers/menu_handlers.py")

    checks = [
        ("schema.py: таблиця saved_quotes",
            "saved_quotes" in sc),
        ("schema.py: поле quote_text",
            "quote_text" in sc),
        ("db.py: save_quote()",
            "save_quote" in db_s),
        ("db.py: get_saved_quotes()",
            "get_saved_quotes" in db_s),
        ("db.py: delete_saved_quote()",
            "delete_saved_quote" in db_s),
        ("scheduler.py: md5 або hashlib для ключа цитати",
            "hashlib" in sched_s or "md5" in sched_s),
        ("scheduler.py: post_type='quote_cache' для пошуку",
            "quote_cache" in sched_s),
        ("menu_handlers.py: savequote: callback",
            "savequote" in mh_s),
        ("menu_handlers.py: del_quote: callback",
            "del_quote" in mh_s),
        ("menu_handlers.py: my_saved_quotes callback",
            "my_saved_quotes" in mh_s),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)

    # Перевірка ліміту збережених цитат (захист від спаму)
    if re.search(r'get_saved_quotes_count|limit.*saved_quotes|MAX.*QUOTES', db_s + mh_s, re.I):
        ok("Ліміт збережених цитат присутній")
    else:
        warn("Немає ліміту збережених цитат -- юзер може зберегти тисячі записів")


def a34_feedback():
    hdr("A34 - FEEDBACK (скринька пропозицій) -- FSM, таблиця, адмін")
    sc = src("src/database/schema.py")
    db_s = src("src/database/db.py")
    mh_s = src("src/routers/menu_handlers.py")
    at_s = src("src/routers/admin_tools.py")

    checks = [
        ("schema.py: таблиця feedback",
            "feedback" in sc),
        ("schema.py: поле status",
            bool(re.search(r'status.*TEXT', sc))),
        ("db.py: save_feedback()",
            "save_feedback" in db_s),
        ("db.py: get_feedback_list()",
            "get_feedback_list" in db_s),
        ("db.py: update_feedback_status()",
            "update_feedback_status" in db_s),
        ("menu_handlers.py: FeedbackStates або feedback FSM",
            "FeedbackState" in mh_s or "feedback" in mh_s.lower()),
        ("menu_handlers.py: вибір типу (bug/suggestion/other)",
            "bug" in mh_s and "suggestion" in mh_s),
        ("menu_handlers.py: state.clear() після збереження",
            bool(re.search(r'state\.clear\(\)', mh_s))),
        ("admin_tools.py: кнопка перегляду фідбеку",
            "feedback" in at_s.lower()),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)

    # FSM clear перевірка окремо для feedback
    feedback_block = re.search(
        r'class FeedbackState\w*\(StatesGroup\)(.*?)(?=\nclass |\Z)', mh_s, re.DOTALL
    )
    if feedback_block:
        states = re.findall(r'(\w+)\s*=\s*State\(\)', feedback_block.group(1))
        ok(f"FeedbackStates: {states}")
        if len(states) < 2:
            warn("Лише 1 стан FSM -- схоже не вистачає вибору типу + введення тексту")
    else:
        warn("FeedbackStates клас не знайдено")


def a35_loyalty_ranks():
    hdr("A35 - LOYALTY RANKS -- пороги, get_user_rank(), профіль")
    db_s = src("src/database/db.py")
    mh_s = src("src/routers/menu_handlers.py")
    pr_s = src("src/routers/profile.py")

    # Перевірка наявності всіх 5 рангів
    RANK_NAMES = ["Кіноглядач", "Кіноман", "Критик", "Синефіл", "Легенда"]
    combined = db_s + mh_s + pr_s
    for rank in RANK_NAMES:
        if rank in combined:
            ok(f"Ранг '{rank}' присутній у коді")
        else:
            warn(f"Ранг '{rank}' не знайдено -- можливо інша назва або відсутній")

    # Перевірка порогів (числа 500, 1500, 3000, 7000)
    THRESHOLDS = [500, 1500, 3000, 7000]
    for t in THRESHOLDS:
        if str(t) in db_s:
            ok(f"Поріг {t} балів визначено в db.py")
        else:
            warn(f"Поріг {t} балів не знайдено в db.py")

    checks = [
        ("db.py: get_user_rank()",
            "get_user_rank" in db_s),
        ("db.py: повертає next_rank та points_to_next",
            "next_rank" in db_s and "points_to_next" in db_s),
        ("profile.py або menu_handlers.py: відображення рангу",
            "get_user_rank" in pr_s or "get_user_rank" in mh_s),
        ("Прогрес-бар або % до наступного рангу",
            bool(re.search(r'progress|прогрес|points_to_next', combined, re.I))),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)


def a36_user_management_v2():
    hdr("A36 - USER MANAGEMENT v2.0 -- ban, admin_log, notes")
    sc = src("src/database/schema.py")
    db_s = src("src/database/db.py")
    at_s = src("src/routers/admin_tools.py")
    mw_s = src("src/middlewares/subscription.py")

    checks = [
        ("schema.py або db.py: поле is_banned у users",
            "is_banned" in sc or "is_banned" in db_s),
        ("schema.py або db.py: поле ban_reason",
            "ban_reason" in sc or "ban_reason" in db_s),
        ("schema.py або db.py: поле admin_note",
            "admin_note" in sc or "admin_note" in db_s),
        ("schema.py: таблиця admin_log",
            "admin_log" in sc),
        ("db.py: ban_user()",
            "ban_user" in db_s),
        ("db.py: unban_user()",
            "unban_user" in db_s),
        ("db.py: set_admin_note()",
            "set_admin_note" in db_s),
        ("db.py: admin_add_points()",
            "admin_add_points" in db_s),
        ("db.py: get_admin_log()",
            "get_admin_log" in db_s),
        ("db.py: search_users()",
            "search_users" in db_s),
        ("admin_tools.py: adm_set:ban або кнопка бану",
            bool(re.search(r'ban|забан', at_s, re.I))),
        ("middleware: перевірка is_banned блокує юзера",
            "is_banned" in mw_s),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)

    # Перевірка що забанений юзер отримує повідомлення, а не тихий ігнор
    if re.search(r'is_banned.*return|заблокован|banned.*answer', mw_s, re.I | re.DOTALL):
        ok("Middleware: забанений юзер отримує відповідь (не тихий дроп)")
    else:
        warn("Middleware: схоже забанений юзер ігнорується без повідомлення -- поганий UX")


def a37_top_movies():
    hdr("A37 - TOP MOVIES СПІЛЬНОТИ -- мін. голоси, фільтри, кнопка")
    db_s = src("src/database/db.py")
    mh_s = src("src/routers/menu_handlers.py")

    checks = [
        ("db.py: get_top_movies()",
            "get_top_movies" in db_s),
        ("db.py: мінімум 3 голоси (захист від викиду)",
            bool(re.search(r'COUNT.*[>=]+\s*3|HAVING.*3|min.*votes.*3', db_s, re.I))),
        ("db.py: AVG(rating) для рейтингу",
            bool(re.search(r'AVG.*rating|avg.*rating', db_s, re.I))),
        ("menu_handlers.py: фільтр week",
            "week" in mh_s),
        ("menu_handlers.py: фільтр month",
            "month" in mh_s),
        ("menu_handlers.py: фільтр all",
            bool(re.search(r'["\']all["\']', mh_s))),
        ("menu_handlers.py: callback menu_top_movies",
            "menu_top_movies" in mh_s or "top_movies" in mh_s),
        ("menu_handlers.py: callback cb_top_movies_period",
            bool(re.search(r'top_movies.*period|period.*top_movies|top_period', mh_s))),
    ]
    for label, passed_ in checks:
        if passed_:
            ok(label)
        else:
            warn(label)

    # Перевірка пустого результату
    if re.search(r'if not.*top|top.*empty|не знайдено.*фільм', db_s + mh_s, re.I):
        ok("Обробка порожнього топу (немає фільмів з 3+ голосами)")
    else:
        warn("Немає обробки порожнього топу -- бот може відправити пустий список")


def a38_rate_limit_protection():
    hdr("A38 - RATE LIMIT / FLOOD PROTECTION")
    combined = "".join(FILES.values())

    checks = [
        ("ThrottlingMiddleware або rate_limit декоратор",
            bool(re.search(r'ThrottlingMiddleware|rate_limit|RateLimitMiddleware|throttle', combined, re.I))),
        ("aiogram Throttling flag",
            bool(re.search(r'throttle_key|flags.*throttling', combined, re.I))),
        ("Захист AI-запитів від флуду (cooldown/cache)",
            bool(re.search(r'cooldown|last_ai_request|ai.*cache|cache.*ai', combined, re.I))),
        ("Захист /search від флуду",
            bool(re.search(r'search.*throttl|throttl.*search|search.*rate', combined, re.I))),
    ]
    any_protection = False
    for label, passed_ in checks:
        if passed_:
            ok(label)
            any_protection = True
        else:
            info(f"Не знайдено: {label}")

    if not any_protection:
        warn("Rate limit захист не виявлено -- бот вразливий до флуду/спаму")
        warn("Рекомендація: додати aiogram-throttling або простий dict-кеш last_request[user_id]")
    else:
        ok("Базовий захист від флуду присутній")


def a39_empty_routers():
    hdr("A39 - ПОРОЖНI РОУТЕРИ (файл є але обробникiв немає)")
    for rpath in ROUTERS:
        s = src(rpath)
        if not s:
            continue  # A01 вже звiтує про вiдсутнiсть
        name = rpath.split("/")[-1]
        handlers = re.findall(r'@router\.(message|callback_query|poll_answer)', s)
        if not handlers:
            err(f"{name}: роутер пiдключено в main.py, але НЕ МАЄ жодного @router-хендлера — мертвий код!")
        else:
            ok(f"{name}: {len(handlers)} хендлер(iв)")


def a40_callback_message_none():
    hdr("A40 - callback.message БЕЗ None-GUARD")
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1].replace(".py", "")
        for m in re.finditer(
            r'async def (\w+)\([^)]*(?:callback)[^)]*\)(.*?)(?=\nasync def |\Z)',
            s, re.DOTALL
        ):
            func_name, body = m.group(1), m.group(2)
            uses_cb_message = bool(re.search(r'callback\.message\.\w+\(', body))
            has_guard = bool(re.search(
                r'if\s+(?:not\s+)?callback\.message|callback\.message\s+is\s+(?:not\s+)?None',
                body
            ))
            # FIX: якщо весь виклик callback.message обгорнутий у try/except — теж захищено
            has_try_wrap = bool(re.search(r'try:.*callback\.message\.\w+\(', body, re.DOTALL))
            if uses_cb_message and not has_guard and not has_try_wrap:
                count = len(re.findall(r'callback\.message\.\w+\(', body))
                warn(f"{name}.{func_name}(): callback.message використовується {count}x без None-guard")


def a41_silent_exceptions():
    hdr("A41 - ТИХI ВИКЛЮЧЕННЯ (except...pass без логування)")
    found = False
    for fpath, s in FILES.items():
        name = fpath.split("/")[-1]
        for m in re.finditer(r'except[^:]*:\s*\n(\s+)(pass|continue)\s*\n', s):
            start = m.end()
            next_lines = s[start:start + 80]
            if 'logger' not in next_lines:
                ln = s[:m.start()].count('\n') + 1
                warn(f"{name}:{ln} — except без логування (pass) — помилка зникне непомiченою")
                found = True
    if not found:
        ok("Тихих виключень не знайдено")


def a42_requirements():
    hdr("A42 - requirements.txt — НАЯВНIСТЬ ТА КЛЮЧОВI ПАКЕТИ")
    req_path = ROOT / "requirements.txt"
    REQUIRED_PACKAGES = [
        "aiogram", "aiohttp", "apscheduler", "cachetools",
        "groq", "google-generativeai", "libsql-client",
        "Pillow", "python-dotenv",
    ]
    if not req_path.exists():
        err("requirements.txt не знайдено — деплой може впасти через вiдсутнi пакети!")
        info("Потрiбнi пакети: " + ", ".join(REQUIRED_PACKAGES))
        return
    req_text = req_path.read_text(encoding="utf-8", errors="replace").lower()
    ok("requirements.txt знайдено")
    for pkg in REQUIRED_PACKAGES:
        if pkg.lower().replace("-", "_") in req_text.replace("-", "_"):
            ok(f"  {pkg}")
        else:
            warn(f"  {pkg} — не знайдено в requirements.txt!")



def a43_subscription_cache_bug():
    hdr("A43 - КЕШ ПІДПИСКИ -- статус перевіряється при поверненні з кешу")
    mw = src("src/middlewares/subscription.py")
    # Шукаємо блок де є timedelta < 1 hour і поруч перевіряється channel_member_status
    cache_block = re.search(
        r'timedelta[^\n]*hour[^\n]*\)(.*?)(?=is_subscribed|_check_subscription)',
        mw, re.DOTALL
    )
    if cache_block:
        block = cache_block.group(1)
        if "channel_member_status" in block or "member_status" in block:
            ok("Кеш перевіряє channel_member_status -- відписані блокуються")
        else:
            err(
                "КЕШ-БАГ: middleware бачить свіжий кеш і пускає юзера НЕ перевіряючи статус! "
                "Відписаний юзер до 1 год має доступ. "
                "Виправлення: у блоці 'if datetime.now() - last_checked < timedelta' "
                "додати: 'if user_db.get(\"channel_member_status\") == \"member\": return await handler(...)'"
            )
    else:
        warn("A43: не вдалось знайти блок кешу підписки")


def a44_morning_movie_photo():
    hdr("A44 - РАНКОВИЙ ПОСТ -- використовує send_photo (не лише текст)")
    ss = src("src/services/scheduler.py")
    morning_match = re.search(
        r'async def post_morning_movie\(self\)(.*?)(?=\n    async def |\Z)', ss, re.DOTALL
    )
    if not morning_match:
        warn("A44: post_morning_movie не знайдено")
        return
    body = morning_match.group(1)
    if "send_photo" in body:
        ok("post_morning_movie використовує send_photo -- пост з постером фільму")
    else:
        err(
            "post_morning_movie використовує лише send_message без постера! "
            "Інші пости (controversial, hidden_gem) мають фото, ранковий — ні. "
            "Виправлення: додати send_photo з poster_url як у post_controversial"
        )


def a45_markdown_escape():
    hdr("A45 - MARKDOWN ESCAPE -- AI-текст екранується перед публікацією")
    ss = src("src/services/scheduler.py")
    # Шукаємо функцію _escape_md або re.escape або .replace для * та _
    has_escape_fn = bool(re.search(r'def _escape_md|escape_md', ss))
    # Перевіряємо чи є хоч якесь екранування
    has_replace_escape = bool(re.search(r"\.replace\(['\"][\*_\[\]`]['\"]", ss))
    # Шукаємо функції що використовують Markdown і вставляють AI res['...']
    md_funcs = re.findall(
        r'async def (post_\w+)\(self\).*?parse_mode=["\']Markdown["\']',
        ss, re.DOTALL
    )
    if has_escape_fn:
        ok("_escape_md функція присутня -- AI текст захищений від зламаного Markdown")
    elif has_replace_escape:
        ok("Markdown-символи екрануються через .replace()")
    else:
        if md_funcs:
            err(
                f"Функції {md_funcs} використовують parse_mode=Markdown з AI-текстом без екранування! "
                "Якщо AI поверне * або _ у тексті -- Telegram не відправить пост. "
                "Виправлення: додати функцію _escape_md() і обгорнути всі res['...'] поля"
            )
        else:
            ok("Markdown без AI-тексту -- екранування не потрібне")


def a46_safe_message_edits():
    hdr("A46 - SAFE MESSAGE EDITS (fallback pattern)")
    # Pattern: edit_text -> edit_caption -> answer
    found_good = 0
    found_bad = 0
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1]

        # Find edit_text calls and check if they are wrapped in try with fallback
        for m in re.finditer(r'\.edit_text\(', s):
            # Look ahead for fallbacks
            ctx = s[m.start():m.start()+500]
            if "edit_caption" in ctx and "answer" in ctx:
                found_good += 1
            else:
                ln = s[:m.start()].count('\n') + 1
                warn(f"{name}:{ln} -- edit_text без повного fallback ланцюга")
                found_bad += 1

    if found_bad == 0:
        ok(f"Всi {found_good} редагувань тексту захищенi")
    else:
        info(f"Захищено: {found_good}, Потребують уваги: {found_bad}")

def a47_safe_deletions():
    hdr("A47 - SAFE MESSAGE DELETIONS (try/except wrap)")
    found_bad = 0
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1]
        for m in re.finditer(r'await\s+[\w\.]+\.delete\(\)', s):
            # Check if previous few lines have 'try:'
            prefix = s[max(0, m.start()-50):m.start()]
            if 'try:' not in prefix:
                ln = s[:m.start()].count('\n') + 1
                warn(f"{name}:{ln} -- .delete() без try/except")
                found_bad += 1
    if found_bad == 0:
        ok("Всi видалення повідомлень безпечнi")

def a48_split_safety():
    hdr("A48 - CALLBACK DATA SPLIT SAFETY (len check)")
    found_bad = 0
    for rpath in ROUTERS:
        s = src(rpath)
        name = rpath.split("/")[-1]
        for m in re.finditer(r'\.split\(["\']-?[:]["\']\)', s):
            # Check if nearby code has 'len(' check
            window = s[m.start():m.start()+150]
            if 'len(' not in window and 'IndexError' not in window:
                ln = s[:m.start()].count('\n') + 1
                warn(f"{name}:{ln} -- split() без перевiрки довжини")
                found_bad += 1
    if found_bad == 0:
        ok("Парсинг callback_data безпечний")

def a49_advanced_flood_protection():
    hdr("A49 - ADVANCED FLOOD PROTECTION (double-tap)")
    mw = src("src/middlewares/throttling.py")
    if "cb_cache" in mw or "double-tap" in mw.lower():
        ok("Double-tap захист у ThrottlingMiddleware")
    else:
        err("Double-tap захист ВIДСУТНIЙ")

def a50_session_persistence():
    hdr("A50 - SESSION PERSISTENCE (FSM guards)")
    # Check if critical handlers check for state data existence
    recommendations = src("src/routers/recommendations.py")
    if "recs" in recommendations and ("not recs" in recommendations or "застаріла" in recommendations):
        ok("Recommendations: guard присутнiй")
    else:
        warn("Recommendations: можливий crash при втратi state")

    onboarding = src("src/routers/onboarding.py")
    if "get_state" in onboarding and "спочатку" in onboarding.lower():
        ok("Onboarding: guard присутнiй")
    else:
        warn("Onboarding: можливий crash при втратi state")


def e_env_check():
    hdr("БЛОК E -- ПЕРЕВIРКА .env ФАЙЛУ")
    env_path = ROOT / ".env"
    env_example_path = ROOT / ".env.example"

    REQUIRED_KEYS = [
        "BOT_TOKEN", "CHANNEL_ID", "GROQ_API_KEY",
        "TMDB_API_KEY", "GEMINI_API_KEY", "ADMIN_IDS",
        "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
        "MONO_CARD", "MONO_NAME",
    ]

    if not env_path.exists():
        warn(".env файл не знайдено (нормально для CI, але потрібен для запуску)")
    else:
        env_text = env_path.read_text(encoding="utf-8", errors="replace")
        env_keys = set(re.findall(r'^([A-Z_]+)\s*=', env_text, re.M))
        ok(f".env знайдено, ключів: {len(env_keys)}")

        for key in REQUIRED_KEYS:
            if key in env_keys:
                # Перевірка що значення не пусте
                m = re.search(rf'^{key}\s*=\s*(.+)$', env_text, re.M)
                val = m.group(1).strip() if m else ""
                if val and val not in ('""', "''", "your_token_here", "CHANGE_ME"):
                    ok(f"{key} -- заповнено")
                else:
                    err(f"{key} -- порожній або placeholder!")
            else:
                err(f"{key} -- відсутній у .env!")

        # Перевірка CHANNEL_ID як числа
        m = re.search(r'^CHANNEL_ID\s*=\s*(-?\d+)', env_text, re.M)
        if m:
            ok(f"CHANNEL_ID = {m.group(1)} (число)")
        elif re.search(r'^CHANNEL_ID\s*=\s*@', env_text, re.M):
            warn("CHANNEL_ID починається з @ -- get_chat_member() може падати, краще числовий ID")

        # Перевірка .env у .gitignore
        gitignore_path = ROOT / ".gitignore"
        if gitignore_path.exists():
            gi = gitignore_path.read_text(encoding="utf-8", errors="replace")
            if ".env" in gi:
                ok(".env додано до .gitignore")
            else:
                err(".env НЕ у .gitignore -- токени потраплять у git!")
        else:
            warn(".gitignore не знайдено")

    if env_example_path.exists():
        ok(".env.example існує -- добра практика")
    else:
        warn(".env.example відсутній -- складно онбордити нових розробників")

# ══════════════════════════════════════════════════════════════════════════════
#  БЛОК B -- СИМУЛЯЦIЯ КОРИСТУВАЧА
# ══════════════════════════════════════════════════════════════════════════════

def check_flow(label: str, key: str, is_cmd: bool = False):
    global issues
    if is_cmd:
        ok_ = key in CMDS
    else:
        ok_, _ = is_handled(key)
    icon = "OK " if ok_ else "ERR"
    col = G if ok_ else RE
    kind = f"/{key}" if is_cmd else f"cb='{key}'"
    print(f"  {col}{icon} {label:<52}{DM} {kind}{R}")
    if not ok_:
        issues += 1


def b_user_simulation():
    hdr("БЛОК B -- СИМУЛЯЦIЯ КОРИСТУВАЧА (кожна кнопка)")

    print(f"\n  {BO}B1 -- ОНБОРДИНГ{R}")
    check_flow("Старт -> /start", "start", is_cmd=True)
    check_flow("Вибiр жанру genre_Бойовик", "genre_Бойовик")
    check_flow("Жанри готово onboarding_genres_done", "onboarding_genres_done")
    check_flow("Частота freq_daily", "freq_daily")
    check_flow("Частота freq_few_times_week", "freq_few_times_week")
    check_flow("Частота freq_once_week", "freq_once_week")
    check_flow("Частота freq_rarely", "freq_rarely")
    check_flow("Епоха period_classic", "period_classic")
    check_flow("Епоха period_2000s", "period_2000s")
    check_flow("Епоха period_2010s", "period_2010s")
    check_flow("Епоха period_2020s", "period_2020s")
    check_flow("Епоха period_any", "period_any")

    print(f"\n  {BO}B2 -- ГОЛОВНЕ МЕНЮ -- ВСI КНОПКИ{R}")
    kb = src("src/keyboards/main_menu.py")
    buttons = sorted(set(re.findall(r'callback_data\s*=\s*["\']([^"\']+)["\']', kb)))
    for btn in buttons:
        if btn == "noop":
            continue
        check_flow(f"Кнопка '{btn}'", btn)
    check_flow("noop (роздiльники меню)", "noop")
    check_flow("/menu команда", "menu", is_cmd=True)
    check_flow("/help команда", "help", is_cmd=True)

    print(f"\n  {BO}B3 -- ПОШУК{R}")
    check_flow("/search команда", "search", is_cmd=True)
    check_flow("Результат -> картка фiльму movie_id:X", "movie_id:12345")
    check_flow("Картка -> Watchlist wl_add:X", "wl_add:12345")
    check_flow("Картка -> Оцiнити rate:X", "rate:12345")
    check_flow("Вибiр оцiнки set_rating:X:Y", "set_rating:12345:8")
    check_flow("Картка -> Схожi similar:X", "similar:12345")
    check_flow("Назад до результатiв back_to_search", "back_to_search")
    check_flow("Назад до меню back_to_menu", "back_to_menu")

    print(f"\n  {BO}B4 -- ДОБIРКА ДНЯ{R}")
    check_flow("Вiдкрити добiрку menu_daily_picks", "menu_daily_picks")
    check_flow("Оновити добiрку (premium)", "refresh_daily_picks")

    print(f"\n  {BO}B5 -- AI-РЕКОМЕНДАЦII{R}")
    check_flow("Вiдкрити AI-рекомендацii menu_ai_rec", "menu_ai_rec")
    check_flow("Наступна рекомендацiя next_ai_rec", "next_ai_rec")

    print(f"\n  {BO}B6 -- ПО НАСТРОЮ{R}")
    check_flow("Вiдкрити вибiр настрою menu_mood", "menu_mood")
    check_flow("Настрiй sad", "mood_pick:sad")
    check_flow("Настрiй romantic", "mood_pick:romantic")
    check_flow("Настрiй angry", "mood_pick:angry")
    check_flow("Настрiй adrenaline", "mood_pick:adrenaline")
    check_flow("Настрiй funny", "mood_pick:funny")
    check_flow("Настрiй thoughtful", "mood_pick:thoughtful")

    print(f"\n  {BO}B7 -- МIЙ СПИСОК{R}")
    check_flow("Вiдкрити список menu_watchlist", "menu_watchlist")
    check_flow("Вкладка want", "wl_tab:want")
    check_flow("Вкладка watching", "wl_tab:watching")
    check_flow("Вкладка watched", "wl_tab:watched")
    check_flow("Управляти фiльмом wl_manage:X", "wl_manage:12345")
    check_flow("Змiнити статус -> want", "wl_set:12345:want")
    check_flow("Змiнити статус -> watching", "wl_set:12345:watching")
    check_flow("Змiнити статус -> watched", "wl_set:12345:watched")
    check_flow("Видалити wl_del:X", "wl_del:12345")

    print(f"\n  {BO}B8 -- ОЦIНКИ{R}")
    check_flow("Список оцiнок menu_ratings", "menu_ratings")

    print(f"\n  {BO}B9 -- СТАТИСТИКА / ЛIДЕРБОРД / ДОСЯГНЕННЯ{R}")
    check_flow("Статистика menu_stats", "menu_stats")
    check_flow("Лiдерборд menu_leaderboard", "menu_leaderboard")
    check_flow("Досягнення menu_achievements", "menu_achievements")
    check_flow("Сповiщення menu_notifications", "menu_notifications")
    check_flow("Toggle сповiщень profile_notifications", "profile_notifications")
    check_flow("Допомога menu_help", "menu_help")

    print(f"\n  {BO}B10 -- СВАЙП-РЕЖИМ{R}")
    check_flow("Старт свайпу menu_swipe", "menu_swipe")
    check_flow("Лайк swipe_like:X", "swipe_like:12345")
    check_flow("Дизлайк swipe_dislike:X", "swipe_dislike:12345")

    print(f"\n  {BO}B11 -- ГРА -- ВГАДАЙ РЕЙТИНГ{R}")
    check_flow("Старт гри menu_guess", "menu_guess")
    check_flow("Вiдповiдь guess_val:X:Y", "guess_val:12345:7")

    print(f"\n  {BO}B12 -- РАЗОМ (JOINT WATCH){R}")
    check_flow("Вiдкрити Разом menu_together", "menu_together")
    check_flow("Створити сесiю joint_create", "joint_create")
    check_flow("Почати свайп joint_start:X", "joint_start:abc123")
    check_flow("Голосувати лайк joint_vote:X:Y:1", "joint_vote:abc:12345:1")
    check_flow("Голосувати дизлайк joint_vote:X:Y:0", "joint_vote:abc:12345:0")

    print(f"\n  {BO}B13 -- ПРОФIЛЬ{R}")
    check_flow("/profile команда", "profile", is_cmd=True)
    check_flow("Профiль з меню menu_profile", "menu_profile")
    check_flow("Реферальна програма profile_referral", "profile_referral")

    print(f"\n  {BO}B14 -- ДОНАТ{R}")
    check_flow("/donate команда", "donate", is_cmd=True)
    check_flow("Донат menu_donate", "menu_donate")
    check_flow("Пiдтвердити донат confirm_donate", "confirm_donate")

    print(f"\n  {BO}B15 -- ПIДПИСКА-GATE{R}")
    check_flow("Перевiрити пiдписку subscribe_check", "subscribe_check")

    print(f"\n  {BO}B16 -- СКРИНЬКА ПРОПОЗИЦIЙ (v2.0){R}")
    check_flow("Вiдкрити скриньку menu_feedback", "menu_feedback")
    check_flow("Тип: баг feedback_type:bug", "feedback_type:bug")
    check_flow("Тип: пропозицiя feedback_type:suggestion", "feedback_type:suggestion")
    check_flow("Тип: iнше feedback_type:other", "feedback_type:other")
    check_flow("Скасувати фiдбек feedback_cancel", "feedback_cancel")

    print(f"\n  {BO}B17 -- ЗБЕРЕЖЕНI ЦИТАТИ (v2.0){R}")
    check_flow("Зберегти цитату savequote:XXXX", "savequote:abc12345")
    check_flow("Мої цитати my_saved_quotes", "my_saved_quotes")
    check_flow("Видалити цитату del_quote:1", "del_quote:1")

    print(f"\n  {BO}B18 -- ТОП ФIЛЬМIВ СПIЛЬНОТИ (v2.0){R}")
    check_flow("Топ фiльмiв menu_top_movies", "menu_top_movies")
    check_flow("Фiльтр: тиждень top_period:week", "top_period:week")
    check_flow("Фiльтр: мiсяць top_period:month", "top_period:month")
    check_flow("Фiльтр: всi часи top_period:all", "top_period:all")


# ══════════════════════════════════════════════════════════════════════════════
#  БЛОК C -- СИМУЛЯЦIЯ АДМIНА
# ══════════════════════════════════════════════════════════════════════════════

def c_admin_simulation():
    hdr("БЛОК C -- СИМУЛЯЦIЯ АДМIНА")
    as_ = src("src/routers/admin_tools.py")

    print(f"\n  {BO}C1 -- ВХIД В АДМIН-ПАНЕЛЬ{R}")
    check_flow("/admin команда", "admin", is_cmd=True)
    check_flow("Повернення до панелi admin_panel", "admin_panel")

    print(f"\n  {BO}C2 -- РОЗСИЛКА{R}")
    check_flow("Вiдкрити розсилку admin_broadcast", "admin_broadcast")
    check_flow("Пiдтвердити розсилку confirm_broadcast", "confirm_broadcast")

    print(f"\n  {BO}C3 -- УПРАВЛIННЯ ЮЗЕРОМ{R}")
    check_flow("Вiдкрити пошук admin_user_manage", "admin_user_manage")
    check_flow("Видати спонсора adm_set:sponsor:X", "adm_set:sponsor:123456789")
    check_flow("Додати 100 балiв adm_set:points100:X", "adm_set:points100:123456789")

    print(f"\n  {BO}C4 -- БIЙ ФIЛЬМIВ{R}")
    check_flow("Створити опитування admin_create_battle", "admin_create_battle")

    print(f"\n  {BO}C5 -- СТАТИСТИКА БОТА{R}")
    check_flow("Статистика (admin) admin_stats", "admin_stats")
    check_flow("Закрити повiдомлення delete_msg", "delete_msg")

    print(f"\n  {BO}C6 -- БЕЗПЕКА ADMIN ХЕНДЛЕРIВ{R}")
    for m in re.finditer(
        r'@router\.callback_query\(F\.data\s*==\s*["\']admin_(\w+)["\']([^)]*)\)', as_
    ):
        btn, ctx = m.group(1), m.group(2)
        if "admin_filter" in ctx:
            ok(f"admin_{btn}: admin_filter")
        else:
            err(f"admin_{btn}: НЕМАЄ admin_filter -- SECURITY HOLE!")

    m = re.search(
        r'@router\.callback_query\(F\.data\.startswith\(["\']adm_set["\']([^)]*)\)', as_
    )
    if m:
        ctx = m.group(1)
        if "admin_filter" in ctx:
            ok("adm_set: prefix -> admin_filter")
        else:
            err("adm_set: хендлер БЕЗ admin_filter -- критична дiрка безпеки!")

    print(f"\n  {BO}C7 -- POLL ANSWER HANDLER{R}")
    if "@router.poll_answer()" in as_:
        ok("@router.poll_answer() хендлер присутнiй")
    else:
        err("@router.poll_answer() вiдсутнiй -- голоси за фiльми не рахуватимуться!")

    print(f"\n  {BO}C8 -- CONFIRM_BROADCAST GUARD{R}")
    m = re.search(
        r'@router\.callback_query\(F\.data\s*==\s*["\']confirm_broadcast["\']([^)]*)\)', as_
    )
    if m:
        ctx = m.group(1)
        if "BroadcastStates" in ctx:
            ok("confirm_broadcast: FSM state guard")
        else:
            err("confirm_broadcast: немає FSM state -> replay attack!")
        if "admin_filter" in ctx:
            ok("confirm_broadcast: admin_filter")
        else:
            err("confirm_broadcast: немає admin_filter!")

    print(f"\n  {BO}C9 -- USER MANAGEMENT v2.0{R}")
    check_flow("Забанити юзера adm_set:ban:X", "adm_set:ban:123456789")
    check_flow("Розбанити юзера adm_set:unban:X", "adm_set:unban:123456789")
    check_flow("Додати 500 балiв adm_set:points500:X", "adm_set:points500:123456789")
    check_flow("Нотатка до юзера adm_set:note:X", "adm_set:note:123456789")
    check_flow("Надiслати повiдомлення юзеру adm_set:msg:X", "adm_set:msg:123456789")

    print(f"\n  {BO}C10 -- ФIДБЕК (АДМIН){R}")
    check_flow("Скринька фiдбеку admin_feedback", "admin_feedback")
    check_flow("Переглянути фiдбек feedback_view:1", "feedback_view:1")
    check_flow("Змiнити статус фiдбеку feedback_status:1:done", "feedback_status:1:done")

    print(f"\n  {BO}C11 -- ЛОГ ДIЙ АДМIНА{R}")
    check_flow("Лог дiй admin_log", "admin_log")


# ══════════════════════════════════════════════════════════════════════════════
#  БЛОК D -- MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════════════

def d_middleware():
    hdr("БЛОК D -- MIDDLEWARE")
    mw = src("src/middlewares/subscription.py")
    ms = src("main.py")
    checks = [
        ("SubscriptionMiddleware визначено", "SubscriptionMiddleware" in mw),
        ("Зареєстровано для message", "message.outer_middleware" in ms),
        ("Зареєстровано для callback_query", "callback_query.outer_middleware" in ms),
        ("get_chat_member перевiрка", "get_chat_member" in mw),
        ("Кешування з timedelta", "timedelta" in mw),
        ("Спонсор обходить перевiрку", "is_sponsor" in mw),
        ("/start у whitelist", '"/start"' in mw or "'/start'" in mw),
        ("subscribe_check у whitelist", "subscribe_check" in mw),
        ("/help у whitelist", '"/help"' in mw or "'/help'" in mw),
        ("/donate у whitelist", '"/donate"' in mw or "'/donate'" in mw),
        ("_check_subscription -> False при помилцi", "return False" in mw),
    ]
    for label, ok_ in checks:
        if ok_:
            ok(label)
        else:
            warn(label)

    if re.search(r'if\s+not\s+user_db|if\s+user_db\s+is\s+None', mw):
        ok("None-guard пiсля re-fetch user_db")
    else:
        warn("Немає None-guard пiсля re-fetch user_db -- AttributeError якщо БД впаде")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BO}{'='*72}")
    print(f"  NeNetflixBot -- ULTIMATE CHECKER v8")
    print(f"  Файлiв знайдено: {len(FILES)}   |   Корiнь: {ROOT}")
    print(f"{'='*72}{R}")

    # Блок A: статичний аналiз
    a01_file_existence()
    a02_imports()
    a03_duplicate_handlers()
    a04_db_methods()
    a05_tmdb_methods()
    a06_ai_null_checks()
    a07_schema()
    a08_config()
    a09_prompts()
    a10_fsm()
    a11_router_order()
    a12_callback_length()
    a13_markdown_bold()
    a14_parse_mode_mix()
    a15_stale_keyboard()
    a16_html_injection()
    a17_bare_except()
    a18_api_no_try()
    a19_hardcoded_secrets()
    a20_n_plus_one()
    a21_json_text_collision()
    a22_channel_id_type()
    a23_admin_filter()
    a24_broadcast_guard()
    a25_recommender()
    a26_scheduler()
    a27_deeplinks()
    a28_none_guards()
    a29_blocking_calls()
    a30_missing_await()
    a31_prefix_collisions()
    # v2.0 перевiрки
    a32_watch_providers()
    a33_saved_quotes()
    a34_feedback()
    a35_loyalty_ranks()
    a36_user_management_v2()
    a37_top_movies()
    a38_rate_limit_protection()
    # v3.0 нові перевірки
    a39_empty_routers()
    a40_callback_message_none()
    a41_silent_exceptions()
    a42_requirements()
    a43_subscription_cache_bug()
    a44_morning_movie_photo()
    a45_markdown_escape()
    # v8 нові перевірки
    a46_safe_message_edits()
    a47_safe_deletions()
    a48_split_safety()
    a49_advanced_flood_protection()
    a50_session_persistence()

    # Блок B: симуляцiя користувача
    b_user_simulation()

    # Блок C: симуляцiя адмiна
    c_admin_simulation()

    # Блок D: middleware
    d_middleware()

    # Блок E: .env перевiрка
    e_env_check()

    # Фiнальний звiт
    w = 72
    print(f"\n{BO}{'='*w}{R}")
    print(f"{BO}  ФIНАЛЬНИЙ ЗВIТ{R}")
    print(f"{'='*w}")
    print(f"\n  {G}{BO}OK   Passed  : {passed}{R}")
    print(f"  {Y}{BO}WRN  Warnings: {warnings}{R}")
    if issues == 0:
        print(f"\n  {G}{BO}НУЛЬ ПОМИЛОК -- бот готовий до деплою!{R}\n")
    else:
        col = RE if issues > 5 else Y
        print(f"  {col}{BO}ERR  Errors  : {issues}{R}")
        print(f"\n  Спочатку виправ ERR, потiм WRN.")
        print(f"  {DM}Запусти знову пiсля виправлень.{R}\n")

    sys.exit(0 if issues == 0 else 1)