import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active")

def run_port():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

threading.Thread(target=run_port, daemon=True).start()
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import asyncio
import html
import random
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ================================================================
# CONFIG
# ================================================================

BOT_TOKEN = "8512567755:AAEpYNZNZPxvO2ZtMCaVT2kuhwSFL8HSH7o"

# Example:
# ADMIN_IDS = {123456789}
ADMIN_IDS = {6760314470}

DB_PATH = "minecraft_bot.db"

MESSAGE_DELETE_SECONDS = 10

BOSS_ATTACK_COOLDOWN = 2.0
DUEL_ATTACK_COOLDOWN = 3.0

STRENGTH_DURATION = 30
STRENGTH_MULTIPLIER = 1.50

SHIELD_MULTIPLIER = 0.50

DUEL_HP_USES = 5
DUEL_SHIELD_USES = 2
DUEL_STRENGTH_USES = 1

STARTING_COINS = 1000

# ================================================================
# DATABASE
# ================================================================

db = sqlite3.connect(
    DB_PATH,
    check_same_thread=False,
)
db.row_factory = sqlite3.Row

db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA foreign_keys=ON")


def init_database():
    """Create every table used by the bot."""

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            coins INTEGER NOT NULL DEFAULT 1000,
            xp INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            total_damage INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL,
            item TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, item)
        );

        CREATE TABLE IF NOT EXISTS bosses (
            boss_key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0,
            hp INTEGER NOT NULL DEFAULT 0,
            max_hp INTEGER NOT NULL DEFAULT 0,
            spawned_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS boss_damage (
            boss_key TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            damage INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (boss_key, user_id)
        );

        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            correct INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            player1 INTEGER NOT NULL,
            player2 INTEGER NOT NULL,
            hp1 INTEGER NOT NULL,
            hp2 INTEGER NOT NULL,
            max_hp1 INTEGER NOT NULL,
            max_hp2 INTEGER NOT NULL,
            turn_user INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            winner INTEGER DEFAULT NULL,
            loser INTEGER DEFAULT NULL,
            created_at REAL NOT NULL DEFAULT 0,
            finished_at REAL DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS duel_stats (
            duel_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            hp_uses INTEGER NOT NULL DEFAULT 0,
            shield_uses INTEGER NOT NULL DEFAULT 0,
            strength_uses INTEGER NOT NULL DEFAULT 0,
            strength_until REAL NOT NULL DEFAULT 0,
            shield_active INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (duel_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS hall_of_fame (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            title TEXT NOT NULL,
            value INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # Migrations for existing databases.
    quiz_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(quizzes)").fetchall()
    }
    if "creator_message_id" not in quiz_columns:
        db.execute(
            "ALTER TABLE quizzes ADD COLUMN creator_message_id INTEGER DEFAULT 0"
        )

    duel_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(duels)").fetchall()
    }
    if "message_id" not in duel_columns:
        db.execute(
            "ALTER TABLE duels ADD COLUMN message_id INTEGER DEFAULT 0"
        )

    db.commit()


# ================================================================
# RANK SYSTEM
# ================================================================

# name, required xp, hp, base damage
RANKS = [
    ("Novice", 0, 900, 90),
    ("Warrior", 2500, 930, 100),
    ("Elite", 6000, 970, 110),
    ("Elite Warrior", 11000, 1010, 120),
    ("Killer", 18000, 1060, 135),
    ("Master", 28000, 1120, 150),
    ("Grandmaster", 42000, 1200, 165),
    ("Legend", 60000, 1320, 180),
    ("Mythic", 85000, 1500, 200),
    ("Emperor", 120000, 2000, 225),
]


def get_rank_by_xp(value: int):
    """Return the strongest rank unlocked by XP."""
    selected = RANKS[0]

    for rank_data in RANKS:
        if value >= rank_data[1]:
            selected = rank_data

    return selected


def get_rank(user_id: int):
    user = get_user(user_id)

    if user is None:
        return RANKS[0]

    return get_rank_by_xp(user["xp"])


def rank_name(user_id: int) -> str:
    return get_rank(user_id)[0]


def rank_hp(user_id: int) -> int:
    return get_rank(user_id)[2]


def rank_damage(user_id: int) -> int:
    return get_rank(user_id)[3]


def next_rank(user_id: int):
    current = get_rank(user_id)

    for rank_data in RANKS:
        if rank_data[1] > current[1]:
            return rank_data

    return None


# ================================================================
# BOSS CONFIG
# ================================================================

# key:
#   display name
#   max HP
#   reward coins
#   reward XP
#   minimum damage
#   maximum damage
BOSSES = {
    "wither": {
        "name": "Wither",
        "hp": 2500,
        "coins": 2600,
        "xp": 1800,
        "min_damage": 70,
        "max_damage": 130,
    },
    "enderdragon": {
        "name": "Ender Dragon",
        "hp": 4200,
        "coins": 5000,
        "xp": 3200,
        "min_damage": 90,
        "max_damage": 160,
    },
    "warden": {
        "name": "Warden",
        "hp": 5200,
        "coins": 6800,
        "xp": 4300,
        "min_damage": 110,
        "max_damage": 180,
    },
    "qishloqi": {
        "name": "Qishloqi Boss",
        "hp": 7000,
        "coins": 9000,
        "xp": 5600,
        "min_damage": 130,
        "max_damage": 205,
    },
    "doncarlo": {
        "name": "DONCARLO",
        "hp": 10000,
        "coins": 15000,
        "xp": 9000,
        "min_damage": 160,
        "max_damage": 250,
    },
}


BOSS_ALIASES = {
    "wither": "wither",
    "with": "wither",
    "ender": "enderdragon",
    "enderdragon": "enderdragon",
    "ender_dragon": "enderdragon",
    "dragon": "enderdragon",
    "warden": "warden",
    "qishloqi": "qishloqi",
    "qishloqi_boss": "qishloqi",
    "qishloqiboss": "qishloqi",
    "doncarlo": "doncarlo",
    "doncarletto": "doncarlo",
}


# ================================================================
# ITEM SYSTEM
# ================================================================

ITEMS = {
    "xp": {
        "name": "🧪 XP Potion",
        "price": 350,
        "description": "XP beradi.",
    },
    "hp": {
        "name": "❤️ HP Potion",
        "price": 500,
        "description": "Duelda HP tiklaydi. Bir duelda 5 marta.",
    },
    "duel_ticket": {
        "name": "🎟️ Duel Ticket",
        "price": 1200,
        "description": "Duel boshlash uchun kerak.",
    },
    "mystery_box": {
        "name": "🎁 Mystery Box",
        "price": 1900,
        "description": "Random reward beradi.",
    },
    "shield": {
        "name": "🛡️ Shield",
        "price": 1000,
        "description": "Keyingi damage 50% kamayadi. Bir duelda 2 marta.",
    },
    "strength": {
        "name": "⚔️ Strength Potion",
        "price": 1600,
        "description": "30 sekund damage x1.5. Bir duelda 1 marta.",
    },
}


# ================================================================
# RUNTIME STATE
# ================================================================

boss_cooldowns = {}
duel_cooldowns = {}

# These are runtime-only and reset when bot restarts.
# Important duel usage counts are also stored in SQLite.
message_tasks = set()


# ================================================================
# GENERAL DATABASE HELPERS
# ================================================================

def now() -> float:
    return time.time()


def ensure_user(tg_user):
    """Create/update user profile."""

    if tg_user is None:
        return

    timestamp = now()

    existing = db.execute(
        "SELECT id FROM users WHERE id = ?",
        (tg_user.id,),
    ).fetchone()

    username = tg_user.username or ""
    first_name = tg_user.first_name or ""

    if existing is None:
        db.execute(
            """
            INSERT INTO users
            (id, username, first_name, coins, xp, wins, losses,
             total_damage, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, 0, 0, ?, ?)
            """,
            (
                tg_user.id,
                username,
                first_name,
                STARTING_COINS,
                timestamp,
                timestamp,
            ),
        )
    else:
        db.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                username,
                first_name,
                timestamp,
                tg_user.id,
            ),
        )

    db.commit()


def get_user(user_id: int):
    return db.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def get_user_by_username(username: str):
    username = username.lstrip("@").strip()

    if not username:
        return None

    return db.execute(
        """
        SELECT *
        FROM users
        WHERE lower(username) = lower(?)
        LIMIT 1
        """,
        (username,),
    ).fetchone()


def display_name(user_id: int) -> str:
    user = get_user(user_id)

    if user is None:
        return str(user_id)

    if user["username"]:
        return "@" + html.escape(user["username"])

    if user["first_name"]:
        return html.escape(user["first_name"])

    return str(user_id)


def change_coins(user_id: int, amount: int):
    db.execute(
        """
        UPDATE users
        SET coins = MAX(0, coins + ?),
            updated_at = ?
        WHERE id = ?
        """,
        (amount, now(), user_id),
    )
    db.commit()


def get_coins(user_id: int) -> int:
    user = get_user(user_id)
    return int(user["coins"]) if user else 0


def change_xp(user_id: int, amount: int):
    db.execute(
        """
        UPDATE users
        SET xp = MAX(0, xp + ?),
            updated_at = ?
        WHERE id = ?
        """,
        (amount, now(), user_id),
    )
    db.commit()


def add_win(user_id: int):
    db.execute(
        """
        UPDATE users
        SET wins = wins + 1,
            updated_at = ?
        WHERE id = ?
        """,
        (now(), user_id),
    )
    db.commit()


def add_loss(user_id: int):
    db.execute(
        """
        UPDATE users
        SET losses = losses + 1,
            updated_at = ?
        WHERE id = ?
        """,
        (now(), user_id),
    )
    db.commit()


def add_total_damage(user_id: int, damage: int):
    db.execute(
        """
        UPDATE users
        SET total_damage = total_damage + ?,
            updated_at = ?
        WHERE id = ?
        """,
        (damage, now(), user_id),
    )
    db.commit()


# ================================================================
# INVENTORY HELPERS
# ================================================================

def item_amount(user_id: int, item: str) -> int:
    result = db.execute(
        """
        SELECT amount
        FROM inventory
        WHERE user_id = ?
          AND item = ?
        """,
        (user_id, item),
    ).fetchone()

    if result is None:
        return 0

    return int(result["amount"])


def add_item(user_id: int, item: str, amount: int):
    if amount <= 0:
        return

    db.execute(
        """
        INSERT INTO inventory(user_id, item, amount)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, item)
        DO UPDATE SET amount = amount + excluded.amount
        """,
        (user_id, item, amount),
    )

    db.commit()


def remove_item(user_id: int, item: str, amount: int = 1) -> bool:
    current = item_amount(user_id, item)

    if current < amount:
        return False

    db.execute(
        """
        UPDATE inventory
        SET amount = amount - ?
        WHERE user_id = ?
          AND item = ?
        """,
        (amount, user_id, item),
    )

    db.commit()
    return True


# ================================================================
# MESSAGE AUTO DELETE
# ================================================================

async def delete_message_later(bot, chat_id: int, message_id: int, seconds: int = 10):
    await asyncio.sleep(seconds)

    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except Exception:
        pass


def schedule_delete(bot, chat_id: int, message_id: int, seconds: int = 10):
    task = asyncio.create_task(
        delete_message_later(
            bot,
            chat_id,
            message_id,
            seconds,
        )
    )

    message_tasks.add(task)

    def remove_task(done_task):
        message_tasks.discard(done_task)

    task.add_done_callback(remove_task)


async def send_temporary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    seconds: int = MESSAGE_DELETE_SECONDS,
    reply_markup=None,
):
    message = await update.effective_chat.send_message(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )

    schedule_delete(
        context.bot,
        message.chat_id,
        message.message_id,
        seconds,
    )

    return message


def schedule_delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE, seconds: int = 10):
    if update.message:
        schedule_delete(
            context.bot,
            update.message.chat_id,
            update.message.message_id,
            seconds,
        )


# ================================================================
# ADMIN HELPERS
# ================================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ================================================================
# DUEL HELPERS
# ================================================================

def active_duel_for_user(user_id: int):
    return db.execute(
        """
        SELECT *
        FROM duels
        WHERE status = 'active'
          AND (player1 = ? OR player2 = ?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, user_id),
    ).fetchone()


def get_duel(duel_id: int):
    return db.execute(
        "SELECT * FROM duels WHERE id = ?",
        (duel_id,),
    ).fetchone()


def duel_opponent(duel_row, user_id: int) -> Optional[int]:
    if duel_row["player1"] == user_id:
        return duel_row["player2"]

    if duel_row["player2"] == user_id:
        return duel_row["player1"]

    return None


def duel_user_hp(duel_row, user_id: int) -> int:
    if duel_row["player1"] == user_id:
        return int(duel_row["hp1"])

    return int(duel_row["hp2"])


def duel_user_max_hp(duel_row, user_id: int) -> int:
    if duel_row["player1"] == user_id:
        return int(duel_row["max_hp1"])

    return int(duel_row["max_hp2"])


def duel_stat(duel_id: int, user_id: int):
    return db.execute(
        """
        SELECT *
        FROM duel_stats
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (duel_id, user_id),
    ).fetchone()


def create_duel_stats(duel_id: int, user_id: int):
    db.execute(
        """
        INSERT OR IGNORE INTO duel_stats
        (duel_id, user_id)
        VALUES (?, ?)
        """,
        (duel_id, user_id),
    )
    db.commit()


def duel_damage_value(user_id: int, duel_id: int) -> int:
    base = rank_damage(user_id)

    stats = duel_stat(duel_id, user_id)

    if stats and float(stats["strength_until"]) > now():
        base = int(base * STRENGTH_MULTIPLIER)

    minimum = max(1, int(base * 0.80))
    maximum = max(minimum, int(base * 1.20))

    return random.randint(minimum, maximum)


async def refresh_duel_message(
    context: ContextTypes.DEFAULT_TYPE,
    duel_row,
):
    message_id = int(duel_row["message_id"] or 0)
    if not message_id:
        return None

    try:
        return await context.bot.edit_message_text(
            chat_id=duel_row["chat_id"],
            message_id=message_id,
            text=duel_text(duel_row),
            parse_mode=ParseMode.HTML,
            reply_markup=duel_keyboard(duel_row["id"]),
        )
    except Exception:
        return None


def duel_text(duel_row) -> str:
    p1 = duel_row["player1"]
    p2 = duel_row["player2"]

    turn = duel_row["turn_user"]

    p1_stats = duel_stat(duel_row["id"], p1)
    p2_stats = duel_stat(duel_row["id"], p2)

    p1_strength = (
        "ON"
        if p1_stats and p1_stats["strength_until"] > now()
        else "OFF"
    )

    p2_strength = (
        "ON"
        if p2_stats and p2_stats["strength_until"] > now()
        else "OFF"
    )

    return (
        "⚔️ <b>DUEL</b>\n\n"
        f"👤 {display_name(p1)} — <b>{rank_name(p1)}</b>\n"
        f"❤️ {duel_row['hp1']}/{duel_row['max_hp1']}\n"
        f"⚔️ Strength: {p1_strength}\n\n"
        f"👤 {display_name(p2)} — <b>{rank_name(p2)}</b>\n"
        f"❤️ {duel_row['hp2']}/{duel_row['max_hp2']}\n"
        f"⚔️ Strength: {p2_strength}\n\n"
        f"🎯 Navbat: <b>{display_name(turn)}</b>\n\n"
        "⚔️ Attack — 3s\n"
        "🧪 Strength — 1 marta / 30s\n"
        "❤️ HP — 5 marta\n"
        "🛡️ Shield — 2 marta"
    )


def duel_keyboard(duel_id: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚔️ ATTACK",
                    callback_data=f"duel_attack:{duel_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🧪 STRENGTH",
                    callback_data=f"duel_strength:{duel_id}",
                ),
                InlineKeyboardButton(
                    "❤️ HP",
                    callback_data=f"duel_hp:{duel_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🛡️ SHIELD",
                    callback_data=f"duel_shield:{duel_id}",
                ),
                InlineKeyboardButton(
                    "🏳️ TASLIM",
                    callback_data=f"duel_forfeit:{duel_id}",
                ),
            ],
        ]
    )


# ================================================================
# BOSS HELPERS
# ================================================================

def get_active_boss():
    return db.execute(
        """
        SELECT *
        FROM bosses
        WHERE active = 1
        ORDER BY spawned_at DESC
        LIMIT 1
        """
    ).fetchone()


def boss_display(boss_row) -> str:
    if not boss_row:
        return "❌ Hozir faol boss yo‘q."

    config = BOSSES.get(boss_row["boss_key"])

    if not config:
        return "❌ Boss konfiguratsiyasi topilmadi."

    return (
        f"👹 <b>{html.escape(config['name'])}</b>\n"
        f"❤️ HP: <b>{boss_row['hp']}/{boss_row['max_hp']}</b>\n\n"
        "⚔️ Zarba berish: <code>/bossattack</code>\n"
        "⏱️ Cooldown: 2 sekund"
    )


def boss_damage_value(user_id: int, boss_key: str) -> int:
    config = BOSSES[boss_key]

    base = rank_damage(user_id)

    low = max(config["min_damage"], int(base * 0.70))
    high = max(low, min(config["max_damage"], int(base * 1.20)))

    return random.randint(low, high)


# ================================================================
# REWARD HELPERS
# ================================================================

DUEL_REWARDS = {
    "coins": 2600,
    "xp": 1500,
    "loser_coins": 350,
    "loser_xp": 250,
}


def finish_duel(duel_id: int, winner: int, loser: int):
    db.execute(
        """
        UPDATE duels
        SET status = 'finished',
            winner = ?,
            loser = ?,
            finished_at = ?
        WHERE id = ?
        """,
        (winner, loser, now(), duel_id),
    )

    db.commit()

    add_win(winner)
    add_loss(loser)

    change_coins(winner, DUEL_REWARDS["coins"])
    change_xp(winner, DUEL_REWARDS["xp"])

    change_coins(
        loser,
        -DUEL_REWARDS["loser_coins"],
    )

    change_xp(
        loser,
        -DUEL_REWARDS["loser_xp"],
    )


def boss_reward_multiplier(place: int) -> float:
    multipliers = {
        1: 1.00,
        2: 0.65,
        3: 0.40,
        4: 0.25,
        5: 0.15,
        6: 0.10,
        7: 0.08,
        8: 0.06,
        9: 0.05,
        10: 0.04,
    }

    if place in multipliers:
        return multipliers[place]

    return 0.10


# ================================================================
# /START
# ================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    text = (
        "⚡ <b>MINECRAFT COMMUNITY BOT</b>\n\n"
        "🎮 Minecraft community uchun economy + duel + boss + quiz tizimi.\n\n"
        "📚 /help — barcha komandalar\n"
        "👤 /profile — profilingiz\n"
        "🏆 /ranks — ranklar\n"
        "🛒 /shop — shop\n"
        "🎒 /inventory — inventory\n"
        "⚔️ /duel @username — duel\n"
        "👹 /boss — boss holati\n"
        "🧠 /quiz — Minecraft quiz"
    )

    await update.effective_chat.send_message(
        text,
        parse_mode=ParseMode.HTML,
    )

    schedule_delete_command(update, context)
# ================================================================
# /HELP
# ================================================================


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    text = (
        "📚 MINECRAFT COMMUNITY BOT — HELP\n\n"
        "👤 PROFILE\n"
        "/profile\n"
        "/ranks\n"
        "/top\n"
        "/inventory\n\n"
        "🛒 SHOP\n"
        "/shop\n"
        "/buy item\n"
        "/openbox\n\n"
        "⚔️ DUEL\n"
        "/duel @username\n"
        "/attack\n"
        "/potion strength\n"
        "/hp\n"
        "/shield\n"
        "/forfeit\n\n"
        "👹 BOSS\n"
        "/boss\n"
        "/bossattack\n"
        "/boss top\n"
        "/spawn doncarlo\n\n"
        "🧠 QUIZ\n"
        "/quiz\n\n"
        "💰 ECONOMY\n"
        "/pay @username 1000\n\n"
    )

    await update.effective_chat.send_message(
        text,
        parse_mode=ParseMode.HTML,
    )

    schedule_delete_command(update, context)

# ================================================================
# /PROFILE
# ================================================================


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    user = get_user(update.effective_user.id)
    current_rank = get_rank_by_xp(user["xp"])
    next_r = next_rank(update.effective_user.id)

    if next_r:
        next_text = (
            f"➡️ Keyingi rank: <b>{next_r[0]}</b>\n"
            f"🎯 Kerakli XP: <b>{next_r[1]}</b>"
        )
    else:
        next_text = "👑 Siz eng yuqori rankdasiz."

    text = (
        "👤 <b>PROFILE</b>\n\n"
        f"🧑 {display_name(user['id'])}\n"
        f"🏆 Rank: <b>{current_rank[0]}</b>\n"
        f"⭐ XP: <b>{user['xp']}</b>\n"
        f"❤️ Rank HP: <b>{current_rank[2]}</b>\n"
        f"⚔️ Damage: <b>{current_rank[3]}</b>\n"
        f"💰 Coins: <b>{user['coins']}</b>\n"
        f"🏅 Wins: <b>{user['wins']}</b>\n"
        f"☠️ Losses: <b>{user['losses']}</b>\n"
        f"💥 Total Damage: <b>{user['total_damage']}</b>\n\n"
        f"{next_text}"
    )

    await update.effective_chat.send_message(
        text,
        parse_mode=ParseMode.HTML,
    )

    schedule_delete_command(update, context)


# ================================================================
# /RANKS
# ================================================================

async def ranks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    lines = [
        "🏆 <b>RANK SYSTEM</b>",
        "",
        "Rank oshgani sari HP va damage ham oshadi.",
        "",
    ]

    for index, rank_data in enumerate(RANKS, 1):
        name_, required_xp, hp_, damage_ = rank_data

        lines.append(
            f"{index}. <b>{name_}</b> — "
            f"⭐ {required_xp} XP | "
            f"❤️ {hp_} | "
            f"⚔️ {damage_}"
        )

    lines.extend(
        [
            "",
            "👑 <b>EMPEROR</b> — ❤️ 2000 HP",
        ]
    )

    await update.effective_chat.send_message(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

    schedule_delete_command(update, context)


# ================================================================
# /TOP
# ================================================================

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    rows = db.execute(
        """
        SELECT *
        FROM users
        ORDER BY xp DESC, wins DESC, coins DESC
        LIMIT 10
        """
    ).fetchall()

    lines = [
        "🏆 <b>TOP 10 PLAYERS</b>",
        "",
    ]

    for index, user in enumerate(rows, 1):
        lines.append(
            f"{index}. {display_name(user['id'])} — "
            f"<b>{rank_name(user['id'])}</b> | "
            f"⭐ {user['xp']} | "
            f"🏅 {user['wins']}"
        )

    if not rows:
        lines.append("Hali playerlar yo‘q.")

    await update.effective_chat.send_message(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

    schedule_delete_command(update, context)


# ================================================================
# /SHOP
# ================================================================

def shop_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🧪 XP",
                    callback_data="shop:xp",
                ),
                InlineKeyboardButton(
                    "❤️ HP",
                    callback_data="shop:hp",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎟️ Ticket",
                    callback_data="shop:duel_ticket",
                ),
                InlineKeyboardButton(
                    "🎁 Mystery",
                    callback_data="shop:mystery_box",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🛡️ Shield",
                    callback_data="shop:shield",
                ),
                InlineKeyboardButton(
                    "⚔️ Strength",
                    callback_data="shop:strength",
                ),
            ],
        ]
    )


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    lines = [
        "🛒 <b>SHOP</b>",
        "",
        f"💰 Sizda: <b>{get_coins(update.effective_user.id)}</b> coin",
        "",
    ]

    for item_key, data in ITEMS.items():
        lines.append(
            f"{data['name']} — 💰 <b>{data['price']}</b>"
        )
        lines.append(
            f"   └ {data['description']}"
        )

    lines.extend(
        [
            "",
            "👇 Olish uchun tugmani bosing.",
        ]
    )

    message = await update.effective_chat.send_message(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=shop_keyboard(),
    )

    schedule_delete(
        context.bot,
        message.chat_id,
        message.message_id,
        60,
    )

    schedule_delete_command(
        update,
        context,
        60,
    )


# ================================================================
# SHOP CALLBACK
# ================================================================

async def shop_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    item: str,
):
    user_id = query.from_user.id
    ensure_user(query.from_user)

    if item not in ITEMS:
        await query.answer(
            "❌ Bunday item yo‘q.",
            show_alert=True,
        )
        return

    price = ITEMS[item]["price"]

    if get_coins(user_id) < price:
        await query.answer(
            "❌ Coin yetarli emas.",
            show_alert=True,
        )
        return

    change_coins(
        user_id,
        -price,
    )

    add_item(
        user_id,
        item,
        1,
    )

    await query.answer(
        "✅ Item berildi!",
        show_alert=False,
    )

    try:
        message = await query.message.reply_text(
            f"✅ <b>ITEM BERILDI</b>\n"
            f"{ITEMS[item]['name']} ×1\n"
            f"💰 -{price} coin",
            parse_mode=ParseMode.HTML,
        )

        schedule_delete(
            context.bot,
            message.chat_id,
            message.message_id,
            10,
        )
    except Exception:
        pass


# ================================================================
# /INVENTORY
# ================================================================

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    rows = db.execute(
        """
        SELECT item, amount
        FROM inventory
        WHERE user_id = ?
          AND amount > 0
        ORDER BY item
        """,
        (update.effective_user.id,),
    ).fetchall()

    lines = [
        "🎒 <b>INVENTORY</b>",
        "",
    ]

    if not rows:
        lines.append("📭 Inventory bo‘sh.")
    else:
        for row in rows:
            item_data = ITEMS.get(row["item"])

            if item_data:
                lines.append(
                    f"{item_data['name']} × <b>{row['amount']}</b>"
                )
            else:
                lines.append(
                    f"{row['item']} × <b>{row['amount']}</b>"
                )

    await update.effective_chat.send_message(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

    schedule_delete_command(update, context)


# ================================================================
# /BUY
# ================================================================

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    if not context.args:
        await send_temporary(
            update,
            context,
            "❌ <code>/buy item</code>\n"
            "Masalan: <code>/buy hp</code>",
        )
        schedule_delete_command(update, context)
        return

    item = context.args[0].lower()

    if item not in ITEMS:
        await send_temporary(
            update,
            context,
            "❌ <b>Noto‘g‘ri item.</b>\n"
            "Shopdagi item nomidan foydalaning.",
        )
        schedule_delete_command(update, context)
        return

    price = ITEMS[item]["price"]

    if get_coins(update.effective_user.id) < price:
        await send_temporary(
            update,
            context,
            "❌ Coin yetarli emas.",
        )
        schedule_delete_command(update, context)
        return

    change_coins(
        update.effective_user.id,
        -price,
    )

    add_item(
        update.effective_user.id,
        item,
        1,
    )

    await send_temporary(
        update,
        context,
        f"✅ <b>ITEM BERILDI</b>\n"
        f"{ITEMS[item]['name']} ×1\n"
        f"💰 -{price}",
    )

    schedule_delete_command(update, context)


# ================================================================
# /OPENBOX
# ================================================================

def mystery_reward(user_id: int):
    possible = [
        ("coins", random.randint(700, 2400)),
        ("xp", random.randint(300, 1200)),
        ("hp", random.randint(1, 3)),
        ("shield", 1),
        ("strength", 1),
        ("duel_ticket", 1),
    ]

    item, amount = random.choice(possible)

    if item == "coins":
        change_coins(user_id, amount)
        return f"💰 +{amount} Coins"

    if item == "xp":
        change_xp(user_id, amount)
        return f"⭐ +{amount} XP"

    add_item(
        user_id,
        item,
        amount,
    )

    return f"{ITEMS[item]['name']} ×{amount}"


async def openbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    user_id = update.effective_user.id

    if not remove_item(
        user_id,
        "mystery_box",
        1,
    ):
        await send_temporary(
            update,
            context,
            "❌ Sizda 🎁 Mystery Box yo‘q.",
        )
        schedule_delete_command(update, context)
        return

    reward = mystery_reward(user_id)

    await send_temporary(
        update,
        context,
        f"🎁 <b>MYSTERY BOX OCHILDI!</b>\n\n"
        f"🎉 Reward: {reward}",
    )

    schedule_delete_command(update, context)


# ================================================================
# DUEL CHALLENGE RESOLUTION
# ================================================================

async def resolve_target_from_args(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        return None

    target = context.args[0].strip()

    if target.startswith("@"):
        target = target[1:]

    if not target:
        return None

    return get_user_by_username(target)


# ================================================================
# /DUEL
# ================================================================

async def duel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    challenger = update.effective_user.id

    target_user = await resolve_target_from_args(
        update,
        context,
    )

    if target_user is None:
        await send_temporary(
            update,
            context,
            "❌ Player topilmadi.\n"
            "Misol: <code>/duel @username</code>",
        )
        schedule_delete_command(update, context)
        return

    target = target_user["id"]

    if target == challenger:
        await send_temporary(
            update,
            context,
            "❌ O‘zingiz bilan duel qila olmaysiz.",
        )
        schedule_delete_command(update, context)
        return

    if active_duel_for_user(challenger):
        await send_temporary(
            update,
            context,
            "❌ Siz allaqachon duel ichidasiz.",
        )
        schedule_delete_command(update, context)
        return

    if active_duel_for_user(target):
        await send_temporary(
            update,
            context,
            "❌ Bu player allaqachon duelda.",
        )
        schedule_delete_command(update, context)
        return

    if item_amount(challenger, "duel_ticket") < 1:
        await send_temporary(
            update,
            context,
            "❌ <b>Duel Ticket kerak.</b>\n"
            "🛒 /shop orqali oling.",
        )
        schedule_delete_command(update, context)
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ QABUL",
                    callback_data=f"duel_accept:{challenger}:{target}",
                ),
                InlineKeyboardButton(
                    "❌ RAD",
                    callback_data=f"duel_decline:{challenger}:{target}",
                ),
            ]
        ]
    )

    message = await update.effective_chat.send_message(
        f"⚔️ <b>DUEL CHALLENGE</b>\n\n"
        f"👤 {display_name(challenger)}\n"
        f"      ⬇️\n"
        f"👤 {display_name(target)}\n\n"
        f"🎟️ Challengerda Duel Ticket bo‘lishi kerak.\n"
        f"⏳ Qabul qilish uchun tugmani bosing.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

    schedule_delete_command(
        update,
        context,
        10,
    )


# ================================================================
# DUEL ACCEPT
# ================================================================

async def duel_accept_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    challenger: int,
    target: int,
):
    if query.from_user.id != target:
        await query.answer(
            "❌ Bu duel sizniki emas.",
            show_alert=True,
        )
        return

    ensure_user(query.from_user)

    if active_duel_for_user(challenger):
        await query.answer(
            "❌ Challenger allaqachon duelda.",
            show_alert=True,
        )
        return

    if active_duel_for_user(target):
        await query.answer(
            "❌ Siz allaqachon duelda.",
            show_alert=True,
        )
        return

    if not remove_item(
        challenger,
        "duel_ticket",
        1,
    ):
        await query.answer(
            "❌ Challengerda Duel Ticket yo‘q.",
            show_alert=True,
        )
        return

    hp1 = rank_hp(challenger)
    hp2 = rank_hp(target)

    cursor = db.execute(
        """
        INSERT INTO duels
        (
            chat_id,
            player1,
            player2,
            hp1,
            hp2,
            max_hp1,
            max_hp2,
            turn_user,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            query.message.chat_id,
            challenger,
            target,
            hp1,
            hp2,
            hp1,
            hp2,
            challenger,
            now(),
        ),
    )

    duel_id = cursor.lastrowid

    create_duel_stats(
        duel_id,
        challenger,
    )

    create_duel_stats(
        duel_id,
        target,
    )

    db.execute(
        "UPDATE duels SET message_id = ? WHERE id = ?",
        (query.message.message_id, duel_id),
    )
    db.commit()

    duel_row = get_duel(duel_id)

    try:
        await query.message.edit_text(
            duel_text(duel_row),
            parse_mode=ParseMode.HTML,
            reply_markup=duel_keyboard(duel_id),
        )
    except Exception:
        pass

    await query.answer(
        "⚔️ Duel boshlandi!",
    )


# ================================================================
# DUEL DECLINE
# ================================================================

async def duel_decline_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    challenger: int,
    target: int,
):
    if query.from_user.id != target:
        await query.answer(
            "❌ Bu duel sizniki emas.",
            show_alert=True,
        )
        return

    try:
        await query.message.edit_text(
            "❌ <b>DUEL RAD ETILDI</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await query.answer(
        "Duel rad etildi.",
    )


# ================================================================
# DUEL ATTACK CORE
# ================================================================

async def perform_duel_attack(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    duel_id: int,
    attacker: int,
):
    duel = get_duel(duel_id)

    if duel is None or duel["status"] != "active":
        await query.answer(
            "❌ Duel tugagan.",
            show_alert=True,
        )
        return

    if attacker not in (
        duel["player1"],
        duel["player2"],
    ):
        await query.answer(
            "❌ Bu duel sizniki emas.",
            show_alert=True,
        )
        return

    if duel["turn_user"] != attacker:
        await query.answer(
            "❌ Hozir navbat sizda emas.",
            show_alert=True,
        )
        return

    last_attack = duel_cooldowns.get(
        (duel_id, attacker),
        0,
    )

    remaining = DUEL_ATTACK_COOLDOWN - (
        now() - last_attack
    )

    if remaining > 0:
        await query.answer(
            f"⏱️ {remaining:.1f}s kuting.",
            show_alert=True,
        )
        return

    duel_cooldowns[
        (duel_id, attacker)
    ] = now()

    defender = duel_opponent(
        duel,
        attacker,
    )

    damage = duel_damage_value(
        attacker,
        duel_id,
    )

    defender_stats = duel_stat(
        duel_id,
        defender,
    )

    shielded = (
        defender_stats is not None
        and int(defender_stats["shield_active"]) == 1
    )

    if shielded:
        damage = max(
            1,
            int(damage * SHIELD_MULTIPLIER),
        )

        db.execute(
            """
            UPDATE duel_stats
            SET shield_active = 0
            WHERE duel_id = ?
              AND user_id = ?
            """,
            (
                duel_id,
                defender,
            ),
        )

        db.commit()

    old_hp = duel_user_hp(
        duel,
        defender,
    )

    new_hp = max(
        0,
        old_hp - damage,
    )

    if defender == duel["player1"]:
        db.execute(
            """
            UPDATE duels
            SET hp1 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                new_hp,
                attacker,
                duel_id,
            ),
        )
    else:
        db.execute(
            """
            UPDATE duels
            SET hp2 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                new_hp,
                attacker,
                duel_id,
            ),
        )

    add_total_damage(
        attacker,
        damage,
    )

    db.commit()

    if new_hp <= 0:
        finish_duel(
            duel_id,
            attacker,
            defender,
        )

        await query.message.edit_text(
            f"🏆 <b>DUEL TUGADI!</b>\n\n"
            f"🥇 G‘olib: {display_name(attacker)}\n"
            f"☠️ Mag‘lub: {display_name(defender)}\n\n"
            f"💥 Oxirgi zarba: <b>{damage}</b>\n"
            f"💰 G‘olib: +{DUEL_REWARDS['coins']} coin\n"
            f"⭐ G‘olib: +{DUEL_REWARDS['xp']} XP\n"
            f"💸 Mag‘lub: -{DUEL_REWARDS['loser_coins']} coin\n"
            f"⭐ Mag‘lub: -{DUEL_REWARDS['loser_xp']} XP",
            parse_mode=ParseMode.HTML,
        )

        await query.answer(
            "🏆 G‘alaba!",
        )
        return

    updated = get_duel(
        duel_id,
    )

    shield_text = (
        "\n🛡️ Shield damage'ni kamaytirdi."
        if shielded
        else ""
    )

    try:
        await query.message.edit_text(
            duel_text(updated)
            + "\n\n"
            f"💥 {display_name(attacker)} → "
            f"{display_name(defender)}: "
            f"<b>{damage}</b> damage"
            + shield_text,
            parse_mode=ParseMode.HTML,
            reply_markup=duel_keyboard(duel_id),
        )
    except Exception:
        pass

    await query.answer(
        f"⚔️ {damage} damage!",
    )


# ================================================================
# DUEL STRENGTH
# ================================================================

async def perform_strength(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    duel_id: int,
    user_id: int,
):
    duel = get_duel(duel_id)

    if duel is None or duel["status"] != "active":
        await query.answer(
            "❌ Duel tugagan.",
            show_alert=True,
        )
        return

    if duel["turn_user"] != user_id:
        await query.answer(
            "❌ Navbat sizda emas.",
            show_alert=True,
        )
        return

    stats = duel_stat(
        duel_id,
        user_id,
    )

    if stats is None:
        await query.answer(
            "❌ Duel statistikasi topilmadi.",
            show_alert=True,
        )
        return

    if stats["strength_uses"] >= DUEL_STRENGTH_USES:
        await query.answer(
            "❌ Strength bu duelda 1 marta.",
            show_alert=True,
        )
        return

    if item_amount(
        user_id,
        "strength",
    ) < 1:
        await query.answer(
            "❌ Sizda Strength Potion yo‘q.",
            show_alert=True,
        )
        return

    remove_item(
        user_id,
        "strength",
        1,
    )

    db.execute(
        """
        UPDATE duel_stats
        SET strength_uses = strength_uses + 1,
            strength_until = ?
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (
            now() + STRENGTH_DURATION,
            duel_id,
            user_id,
        ),
    )

    opponent = duel_opponent(
        duel,
        user_id,
    )

    db.execute(
        """
        UPDATE duels
        SET turn_user = ?
        WHERE id = ?
        """,
        (
            opponent,
            duel_id,
        ),
    )

    db.commit()

    updated = get_duel(
        duel_id,
    )

    try:
        await query.message.edit_text(
            duel_text(updated)
            + "\n\n"
            f"⚔️ <b>{display_name(user_id)}</b> "
            f"Strength ishlatdi!\n"
            f"🔥 Damage x{STRENGTH_MULTIPLIER}\n"
            f"⏱️ {STRENGTH_DURATION} sekund",
            parse_mode=ParseMode.HTML,
            reply_markup=duel_keyboard(duel_id),
        )
    except Exception:
        pass

    await query.answer(
        "⚔️ Strength yoqildi!",
    )


# ================================================================
# DUEL HP
# ================================================================

async def perform_hp(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    duel_id: int,
    user_id: int,
):
    duel = get_duel(duel_id)

    if duel is None or duel["status"] != "active":
        await query.answer(
            "❌ Duel tugagan.",
            show_alert=True,
        )
        return

    if duel["turn_user"] != user_id:
        await query.answer(
            "❌ Navbat sizda emas.",
            show_alert=True,
        )
        return

    stats = duel_stat(
        duel_id,
        user_id,
    )

    if stats["hp_uses"] >= DUEL_HP_USES:
        await query.answer(
            "❌ HP Potion 5 marta ishlatilgan.",
            show_alert=True,
        )
        return

    if item_amount(
        user_id,
        "hp",
    ) < 1:
        await query.answer(
            "❌ Sizda HP Potion yo‘q.",
            show_alert=True,
        )
        return

    remove_item(
        user_id,
        "hp",
        1,
    )

    max_hp = duel_user_max_hp(
        duel,
        user_id,
    )

    current_hp = duel_user_hp(
        duel,
        user_id,
    )

    heal = max(
        100,
        int(max_hp * 0.20),
    )

    new_hp = min(
        max_hp,
        current_hp + heal,
    )

    if user_id == duel["player1"]:
        db.execute(
            """
            UPDATE duels
            SET hp1 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                new_hp,
                duel["player2"],
                duel_id,
            ),
        )
    else:
        db.execute(
            """
            UPDATE duels
            SET hp2 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                new_hp,
                duel["player1"],
                duel_id,
            ),
        )

    db.execute(
        """
        UPDATE duel_stats
        SET hp_uses = hp_uses + 1
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (
            duel_id,
            user_id,
        ),
    )

    db.commit()

    updated = get_duel(
        duel_id,
    )

    try:
        await query.message.edit_text(
            duel_text(updated)
            + "\n\n"
            f"❤️ <b>{display_name(user_id)}</b> "
            f"+{new_hp - current_hp} HP tikladi.",
            parse_mode=ParseMode.HTML,
            reply_markup=duel_keyboard(duel_id),
        )
    except Exception:
        pass

    await query.answer(
        f"❤️ +{new_hp - current_hp} HP",
    )


# ================================================================
# DUEL SHIELD
# ================================================================

async def perform_shield(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    duel_id: int,
    user_id: int,
):
    duel = get_duel(duel_id)

    if duel is None or duel["status"] != "active":
        await query.answer(
            "❌ Duel tugagan.",
            show_alert=True,
        )
        return

    if duel["turn_user"] != user_id:
        await query.answer(
            "❌ Navbat sizda emas.",
            show_alert=True,
        )
        return

    stats = duel_stat(
        duel_id,
        user_id,
    )

    if stats["shield_uses"] >= DUEL_SHIELD_USES:
        await query.answer(
            "❌ Shield 2 marta ishlatilgan.",
            show_alert=True,
        )
        return

    if item_amount(
        user_id,
        "shield",
    ) < 1:
        await query.answer(
            "❌ Sizda Shield yo‘q.",
            show_alert=True,
        )
        return

    remove_item(
        user_id,
        "shield",
        1,
    )

    opponent = duel_opponent(
        duel,
        user_id,
    )

    db.execute(
        """
        UPDATE duel_stats
        SET shield_uses = shield_uses + 1,
            shield_active = 1
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (
            duel_id,
            user_id,
        ),
    )

    db.execute(
        """
        UPDATE duels
        SET turn_user = ?
        WHERE id = ?
        """,
        (
            opponent,
            duel_id,
        ),
    )

    db.commit()

    updated = get_duel(
        duel_id,
    )

    try:
        await query.message.edit_text(
            duel_text(updated)
            + "\n\n"
            f"🛡️ <b>{display_name(user_id)}</b> "
            "Shield yoqdi.\n"
            "💥 Keyingi damage 50% kamayadi.",
            parse_mode=ParseMode.HTML,
            reply_markup=duel_keyboard(duel_id),
        )
    except Exception:
        pass

    await query.answer(
        "🛡️ Shield yoqildi!",
    )


# ================================================================
# DUEL FORFEIT
# ================================================================

async def perform_forfeit(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    duel_id: int,
    user_id: int,
):
    duel = get_duel(duel_id)

    if duel is None or duel["status"] != "active":
        await query.answer(
            "❌ Duel tugagan.",
            show_alert=True,
        )
        return

    if user_id not in (
        duel["player1"],
        duel["player2"],
    ):
        await query.answer(
            "❌ Bu duel sizniki emas.",
            show_alert=True,
        )
        return

    opponent = duel_opponent(
        duel,
        user_id,
    )

    finish_duel(
        duel_id,
        opponent,
        user_id,
    )

    try:
        await query.message.edit_text(
            f"🏳️ <b>DUEL TUGADI</b>\n\n"
            f"🏳️ Taslim bo‘lgan: {display_name(user_id)}\n"
            f"🥇 G‘olib: {display_name(opponent)}\n\n"
            f"💰 G‘olib: +{DUEL_REWARDS['coins']}\n"
            f"⭐ G‘olib: +{DUEL_REWARDS['xp']} XP",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await query.answer(
        "Duel tugadi.",
    )


# ================================================================
# /ATTACK
# ================================================================

async def attack_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    duel = active_duel_for_user(
        update.effective_user.id,
    )

    if duel is None:
        await send_temporary(
            update,
            context,
            "❌ Siz duelda emassiz.",
        )
        schedule_delete_command(update, context)
        return

    user_id = update.effective_user.id

    if duel["turn_user"] != user_id:
        await send_temporary(
            update,
            context,
            "❌ Hozir navbat sizda emas.",
        )
        schedule_delete_command(update, context)
        return

    last_attack = duel_cooldowns.get(
        (duel["id"], user_id),
        0,
    )

    remaining = DUEL_ATTACK_COOLDOWN - (
        now() - last_attack
    )

    if remaining > 0:
        await send_temporary(
            update,
            context,
            f"⏱️ Attack cooldown: <b>{remaining:.1f}s</b>",
        )
        schedule_delete_command(update, context)
        return

    duel_cooldowns[
        (duel["id"], user_id)
    ] = now()

    defender = duel_opponent(
        duel,
        user_id,
    )

    damage = duel_damage_value(
        user_id,
        duel["id"],
    )

    defender_stats = duel_stat(
        duel["id"],
        defender,
    )

    shielded = (
        defender_stats
        and defender_stats["shield_active"] == 1
    )

    if shielded:
        damage = max(
            1,
            int(damage * SHIELD_MULTIPLIER),
        )

        db.execute(
            """
            UPDATE duel_stats
            SET shield_active = 0
            WHERE duel_id = ?
              AND user_id = ?
            """,
            (
                duel["id"],
                defender,
            ),
        )

    hp = duel_user_hp(
        duel,
        defender,
    )

    hp = max(
        0,
        hp - damage,
    )

    if defender == duel["player1"]:
        db.execute(
            """
            UPDATE duels
            SET hp1 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                hp,
                user_id,
                duel["id"],
            ),
        )
    else:
        db.execute(
            """
            UPDATE duels
            SET hp2 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                hp,
                user_id,
                duel["id"],
            ),
        )

    add_total_damage(
        user_id,
        damage,
    )

    db.commit()

    if hp <= 0:
        finish_duel(
            duel["id"],
            user_id,
            defender,
        )

        duel_message_id = int(duel["message_id"] or 0)
        if duel_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=duel["chat_id"],
                    message_id=duel_message_id,
                    text=(
                        f"🏆 <b>DUEL TUGADI</b>\n\n"
                        f"🥇 G‘olib: {display_name(user_id)}\n"
                        f"☠️ Mag‘lub: {display_name(defender)}\n"
                        f"💥 Damage: <b>{damage}</b>\n\n"
                        f"💰 +{DUEL_REWARDS['coins']} coin\n"
                        f"⭐ +{DUEL_REWARDS['xp']} XP"
                    ),
                    parse_mode=ParseMode.HTML,
                )
                schedule_delete(
                    context.bot,
                    duel["chat_id"],
                    duel_message_id,
                    10,
                )
            except Exception:
                pass
        else:
            message = await update.effective_chat.send_message(
                f"🏆 <b>DUEL TUGADI</b>\n\n"
                f"🥇 G‘olib: {display_name(user_id)}\n"
                f"☠️ Mag‘lub: {display_name(defender)}\n"
                f"💥 Damage: <b>{damage}</b>\n\n"
                f"💰 +{DUEL_REWARDS['coins']} coin\n"
                f"⭐ +{DUEL_REWARDS['xp']} XP",
                parse_mode=ParseMode.HTML,
            )
            schedule_delete(
                context.bot,
                message.chat_id,
                message.message_id,
                10,
            )

        schedule_delete_command(
            update,
            context,
        )

        return

    updated = get_duel(
        duel["id"],
    )

    await refresh_duel_message(
        context,
        updated,
    )

    await send_temporary(
        update,
        context,
        f"⚔️ <b>ZARBA</b>\n"
        f"💥 {display_name(user_id)} → {display_name(defender)}: "
        f"<b>{damage}</b> damage",
        seconds=10,
    )

    schedule_delete_command(
        update,
        context,
        10,
    )


# ================================================================
# /POTION
# ================================================================

async def potion_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    if not context.args:
        await send_temporary(
            update,
            context,
            "🧪 Foydalanish:\n"
            "<code>/potion strength</code>",
        )
        schedule_delete_command(update, context)
        return

    item = context.args[0].lower()

    if item != "strength":
        await send_temporary(
            update,
            context,
            "❌ Noto‘g‘ri potion.\n"
            "Faqat <code>/potion strength</code>.",
        )
        schedule_delete_command(update, context)
        return

    duel = active_duel_for_user(
        update.effective_user.id,
    )

    if duel is None:
        await send_temporary(
            update,
            context,
            "❌ Strength faqat duelda ishlaydi.",
        )
        schedule_delete_command(update, context)
        return

    user_id = update.effective_user.id

    if duel["turn_user"] != user_id:
        await send_temporary(
            update,
            context,
            "❌ Hozir navbat sizda emas.",
        )
        schedule_delete_command(update, context)
        return

    stats = duel_stat(
        duel["id"],
        user_id,
    )

    if stats["strength_uses"] >= DUEL_STRENGTH_USES:
        await send_temporary(
            update,
            context,
            "❌ Strength bu duelda faqat 1 marta.",
        )
        schedule_delete_command(update, context)
        return

    if not remove_item(
        user_id,
        "strength",
        1,
    ):
        await send_temporary(
            update,
            context,
            "❌ Sizda Strength Potion yo‘q.",
        )
        schedule_delete_command(update, context)
        return

    db.execute(
        """
        UPDATE duel_stats
        SET strength_uses = strength_uses + 1,
            strength_until = ?
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (
            now() + STRENGTH_DURATION,
            duel["id"],
            user_id,
        ),
    )

    db.execute(
        """
        UPDATE duels
        SET turn_user = ?
        WHERE id = ?
        """,
        (
            duel_opponent(duel, user_id),
            duel["id"],
        ),
    )

    db.commit()

    updated = get_duel(
        duel["id"],
    )

    await send_temporary(
        update,
        context,
        f"⚔️ <b>STRENGTH ISHLADI</b>\n"
        f"🔥 Damage x{STRENGTH_MULTIPLIER}\n"
        f"⏱️ {STRENGTH_DURATION} sekund\n"
        f"1/1 foydalanish.",
    )

    # Duel message is separately refreshed through a new message.
    message = await update.effective_chat.send_message(
        duel_text(updated),
        parse_mode=ParseMode.HTML,
        reply_markup=duel_keyboard(duel["id"]),
    )

    schedule_delete(
        context.bot,
        message.chat_id,
        message.message_id,
        60,
    )

    schedule_delete_command(
        update,
        context,
    )


# ================================================================
# /HP
# ================================================================

async def hp_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    user_id = update.effective_user.id

    duel = active_duel_for_user(
        user_id,
    )

    if duel is None:
        await send_temporary(
            update,
            context,
            "❌ HP Potion faqat duelda ishlaydi.",
        )
        schedule_delete_command(update, context)
        return

    if duel["turn_user"] != user_id:
        await send_temporary(
            update,
            context,
            "❌ Hozir navbat sizda emas.",
        )
        schedule_delete_command(update, context)
        return

    stats = duel_stat(
        duel["id"],
        user_id,
    )

    if stats["hp_uses"] >= DUEL_HP_USES:
        await send_temporary(
            update,
            context,
            "❌ HP Potion bu duelda 5 marta ishlatilgan.",
        )
        schedule_delete_command(update, context)
        return

    if not remove_item(
        user_id,
        "hp",
        1,
    ):
        await send_temporary(
            update,
            context,
            "❌ Sizda HP Potion yo‘q.",
        )
        schedule_delete_command(update, context)
        return

    current = duel_user_hp(
        duel,
        user_id,
    )

    maximum = duel_user_max_hp(
        duel,
        user_id,
    )

    heal = max(
        100,
        int(maximum * 0.20),
    )

    new_hp = min(
        maximum,
        current + heal,
    )

    if user_id == duel["player1"]:
        db.execute(
            """
            UPDATE duels
            SET hp1 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                new_hp,
                duel["player2"],
                duel["id"],
            ),
        )
    else:
        db.execute(
            """
            UPDATE duels
            SET hp2 = ?,
                turn_user = ?
            WHERE id = ?
            """,
            (
                new_hp,
                duel["player1"],
                duel["id"],
            ),
        )

    db.execute(
        """
        UPDATE duel_stats
        SET hp_uses = hp_uses + 1
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (
            duel["id"],
            user_id,
        ),
    )

    db.commit()

    await send_temporary(
        update,
        context,
        f"❤️ <b>HP POTION ISHLADI</b>\n"
        f"❤️ +{new_hp - current} HP\n"
        f"🔢 Ishlatish: {stats['hp_uses'] + 1}/{DUEL_HP_USES}",
    )

    schedule_delete_command(
        update,
        context,
    )


# ================================================================
# /SHIELD
# ================================================================

async def shield_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    user_id = update.effective_user.id

    duel = active_duel_for_user(
        user_id,
    )

    if duel is None:
        await send_temporary(
            update,
            context,
            "❌ Shield faqat duelda ishlaydi.",
        )
        schedule_delete_command(update, context)
        return

    if duel["turn_user"] != user_id:
        await send_temporary(
            update,
            context,
            "❌ Hozir navbat sizda emas.",
        )
        schedule_delete_command(update, context)
        return

    stats = duel_stat(
        duel["id"],
        user_id,
    )

    if stats["shield_uses"] >= DUEL_SHIELD_USES:
        await send_temporary(
            update,
            context,
            "❌ Shield bu duelda 2 marta ishlatilgan.",
        )
        schedule_delete_command(update, context)
        return

    if not remove_item(
        user_id,
        "shield",
        1,
    ):
        await send_temporary(
            update,
            context,
            "❌ Sizda Shield yo‘q.",
        )
        schedule_delete_command(update, context)
        return

    opponent = duel_opponent(
        duel,
        user_id,
    )

    db.execute(
        """
        UPDATE duel_stats
        SET shield_uses = shield_uses + 1,
            shield_active = 1
        WHERE duel_id = ?
          AND user_id = ?
        """,
        (
            duel["id"],
            user_id,
        ),
    )

    db.execute(
        """
        UPDATE duels
        SET turn_user = ?
        WHERE id = ?
        """,
        (
            opponent,
            duel["id"],
        ),
    )

    db.commit()

    await send_temporary(
        update,
        context,
        "🛡️ <b>SHIELD ISHLADI</b>\n"
        "💥 Keyingi damage 50% kamayadi.\n"
        "🔢 Ishlatish: "
        f"{stats['shield_uses'] + 1}/{DUEL_SHIELD_USES}",
    )

    schedule_delete_command(
        update,
        context,
    )


# ================================================================
# /FORFEIT
# ================================================================

async def forfeit_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    user_id = update.effective_user.id

    duel = active_duel_for_user(
        user_id,
    )

    if duel is None:
        await send_temporary(
            update,
            context,
            "❌ Siz duelda emassiz.",
        )
        schedule_delete_command(update, context)
        return

    opponent = duel_opponent(
        duel,
        user_id,
    )

    finish_duel(
        duel["id"],
        opponent,
        user_id,
    )

    await send_temporary(
        update,
        context,
        f"🏳️ <b>TASLIM BO‘LDINGIZ</b>\n\n"
        f"🥇 G‘olib: {display_name(opponent)}\n"
        f"💰 G‘olib +{DUEL_REWARDS['coins']}\n"
        f"⭐ G‘olib +{DUEL_REWARDS['xp']} XP",
    )

    schedule_delete_command(
        update,
        context,
    )


# ================================================================
# /BOSS
# ================================================================

async def boss_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    boss_row = get_active_boss()

    await send_temporary(
        update,
        context,
        boss_display(boss_row),
        seconds=20,
    )

    schedule_delete_command(
        update,
        context,
        20,
    )


# ================================================================
# /SPAWN
# ================================================================

async def spawn_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    if not is_admin(
        update.effective_user.id
    ):
        await send_temporary(
            update,
            context,
            "❌ Faqat admin.",
        )
        schedule_delete_command(update, context)
        return

    if not context.args:
        await send_temporary(
            update,
            context,
            "❌ <code>/spawn wither</code>\n"
            "❌ <code>/spawn enderdragon</code>\n"
            "❌ <code>/spawn warden</code>\n"
            "❌ <code>/spawn qishloqi</code>\n"
            "❌ <code>/spawn doncarlo</code>",
        )
        schedule_delete_command(update, context)
        return

    alias = context.args[0].lower()
    boss_key = BOSS_ALIASES.get(alias)

    if boss_key is None:
        await send_temporary(
            update,
            context,
            "❌ <b>Bunday boss yo‘q.</b>",
        )
        schedule_delete_command(update, context)
        return

    active = get_active_boss()

    if active:
        await send_temporary(
            update,
            context,
            "❌ Hozir boshqa boss faol.",
        )
        schedule_delete_command(update, context)
        return

    config = BOSSES[boss_key]

    db.execute(
        """
        INSERT INTO bosses
        (
            boss_key,
            name,
            active,
            hp,
            max_hp,
            spawned_at
        )
        VALUES (?, ?, 1, ?, ?, ?)
        ON CONFLICT(boss_key)
        DO UPDATE SET
            name = excluded.name,
            active = 1,
            hp = excluded.hp,
            max_hp = excluded.max_hp,
            spawned_at = excluded.spawned_at
        """,
        (
            boss_key,
            config["name"],
            config["hp"],
            config["hp"],
            now(),
        ),
    )

    db.execute(
        """
        DELETE FROM boss_damage
        WHERE boss_key = ?
        """,
        (boss_key,),
    )

    db.commit()

    message = await update.effective_chat.send_message(
        f"👹 <b>{html.escape(config['name'])} SPAWN!</b>\n\n"
        f"❤️ HP: <b>{config['hp']}</b>\n"
        f"💰 Reward pool: <b>{config['coins']}</b>\n"
        f"⭐ XP pool: <b>{config['xp']}</b>\n\n"
        "⚔️ <code>/bossattack</code>\n"
        "⏱️ Cooldown: 2 sekund",
        parse_mode=ParseMode.HTML,
    )

    schedule_delete(
        context.bot,
        message.chat_id,
        message.message_id,
        30,
    )

    schedule_delete_command(
        update,
        context,
        30,
    )


# ================================================================
# /DONCARLO
# ================================================================

async def doncarlo_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    # Admin-only shortcut for DONCARLO.
    ensure_user(update.effective_user)

    if not is_admin(
        update.effective_user.id
    ):
        await send_temporary(
            update,
            context,
            "❌ Faqat admin.",
        )
        schedule_delete_command(update, context)
        return

    context.args = ["doncarlo"]

    await spawn_command(
        update,
        context,
    )


# ================================================================
# /BOSSATTACK
# ================================================================

async def boss_attack_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    user_id = update.effective_user.id

    active = get_active_boss()

    if active is None:
        await send_temporary(
            update,
            context,
            "❌ Hozir faol boss yo‘q.",
        )
        schedule_delete_command(update, context)
        return

    last_attack = boss_cooldowns.get(
        user_id,
        0,
    )

    remaining = BOSS_ATTACK_COOLDOWN - (
        now() - last_attack
    )

    if remaining > 0:
        await send_temporary(
            update,
            context,
            f"⏱️ Boss attack cooldown: "
            f"<b>{remaining:.1f}s</b>",
        )
        schedule_delete_command(update, context)
        return

    boss_cooldowns[user_id] = now()

    boss_key = active["boss_key"]
    config = BOSSES[boss_key]

    damage = boss_damage_value(
        user_id,
        boss_key,
    )

    damage = min(
        damage,
        active["hp"],
    )

    new_hp = max(
        0,
        active["hp"] - damage,
    )

    db.execute(
        """
        UPDATE bosses
        SET hp = ?
        WHERE boss_key = ?
        """,
        (
            new_hp,
            boss_key,
        ),
    )

    player_name = (
        get_user(user_id)["username"]
        or get_user(user_id)["first_name"]
        or str(user_id)
    )

    db.execute(
        """
        INSERT INTO boss_damage
        (
            boss_key,
            user_id,
            player_name,
            damage
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(boss_key, user_id)
        DO UPDATE SET
            player_name = excluded.player_name,
            damage = damage + excluded.damage
        """,
        (
            boss_key,
            user_id,
            player_name,
            damage,
        ),
    )

    add_total_damage(
        user_id,
        damage,
    )

    db.commit()

    # Boss is still alive.
    if new_hp > 0:
        message = await update.effective_chat.send_message(
            f"⚔️ <b>ZARBA BERILDI</b>\n\n"
            f"👤 {display_name(user_id)}\n"
            f"👹 {html.escape(config['name'])}\n"
            f"💥 Damage: <b>{damage}</b>\n"
            f"❤️ Boss HP: <b>{new_hp}/{active['max_hp']}</b>",
            parse_mode=ParseMode.HTML,
        )

        schedule_delete(
            context.bot,
            message.chat_id,
            message.message_id,
            10,
        )

        schedule_delete_command(
            update,
            context,
            10,
        )

        return

    # ============================================================
    # BOSS DEFEATED
    # ============================================================

    rows = db.execute(
        """
        SELECT *
        FROM boss_damage
        WHERE boss_key = ?
        ORDER BY damage DESC
        LIMIT 10
        """,
        (boss_key,),
    ).fetchall()

    lines = [
        f"🏆 <b>{html.escape(config['name'])} YIQILDI!</b>",
        "",
        "🏅 <b>TOP DAMAGE</b>",
        "",
    ]

    for place, row in enumerate(rows, 1):
        multiplier = boss_reward_multiplier(
            place
        )

        coins_reward = max(
            100,
            int(config["coins"] * multiplier),
        )

        xp_reward = max(
            100,
            int(config["xp"] * multiplier),
        )

        change_coins(
            row["user_id"],
            coins_reward,
        )

        change_xp(
            row["user_id"],
            xp_reward,
        )

        if place == 1:
            medal = "🥇"
        elif place == 2:
            medal = "🥈"
        elif place == 3:
            medal = "🥉"
        else:
            medal = f"{place}."

        lines.append(
            f"{medal} {html.escape(row['player_name'])}\n"
            f"   💥 {row['damage']} damage | "
            f"💰 +{coins_reward} | "
            f"⭐ +{xp_reward} XP"
        )

    if not rows:
        lines.append(
            "Damage bergan player topilmadi."
        )

    db.execute(
        """
        UPDATE bosses
        SET active = 0,
            hp = 0
        WHERE boss_key = ?
        """,
        (boss_key,),
    )

    db.commit()

    message = await update.effective_chat.send_message(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

    schedule_delete(
        context.bot,
        message.chat_id,
        message.message_id,
        10,
    )

    schedule_delete_command(
        update,
        context,
        10,
    )


# ================================================================
# /BOSS TOP
# ================================================================

async def boss_top_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    active = get_active_boss()

    if active is None:
        await send_temporary(
            update,
            context,
            "❌ Hozir faol boss yo‘q.",
        )
        schedule_delete_command(update, context)
        return

    rows = db.execute(
        """
        SELECT *
        FROM boss_damage
        WHERE boss_key = ?
        ORDER BY damage DESC
        LIMIT 10
        """,
        (active["boss_key"],),
    ).fetchall()

    lines = [
        f"🏅 <b>{html.escape(active['name'])} TOP DAMAGE</b>",
        "",
    ]

    if not rows:
        lines.append(
            "Hali hech kim damage bermagan."
        )
    else:
        for index, row in enumerate(
            rows,
            1,
        ):
            lines.append(
                f"{index}. "
                f"{html.escape(row['player_name'])} — "
                f"💥 {row['damage']}"
            )

    await send_temporary(
        update,
        context,
        "\n".join(lines),
        seconds=20,
    )

    schedule_delete_command(
        update,
        context,
        20,
    )


# ================================================================
# QUIZ DATABASE
# ================================================================

# ================================================================
# QUIZ DATABASE
# ================================================================

# ================================================================
# QUIZ DATABASE (FAQAT MINECRAFT)
# ================================================================

QUIZ_DATA = [
    ("Minecraft Java'da Nether portalining minimal o'lchami qanday?",
     ["3x3", "2x3", "4x5", "5x5"], 2),

    ("Java Edition'da maksimal enchantment levelini oshirish uchun qaysi buyruq ishlatiladi?",
     ["/give", "/effect", "/enchant", "/attribute"], 2),

    ("Warden qaysi mobni ko'rish orqali emas, asosan qaysi mexanizm orqali sezadi?",
     ["Light", "Vibration", "Water", "Fire"], 1),

    ("Sculk Sensor qaysi hodisani aniqlay oladi?",
     ["Faqat yorug'lik", "Faqat moblar", "Vibrations", "Faqat redstone"], 2),

    ("Sculk Catalyst mob o'lganda nima hosil qiladi?",
     ["Obsidian", "Sculk", "Soul Sand", "Amethyst"], 1),

    ("Warden qaysi effektni o'yinchiga beradi?",
     ["Blindness", "Mining Fatigue", "Weakness", "Darkness"], 3),

    ("Beacon maksimal kuchda nechta qatlamli piramidaga ega bo'ladi?",
     ["3", "4", "5", "6"], 1),

    ("Beacon piramidasining eng pastki qatlami maksimal nechta blokdan iborat?",
     ["9", "25", "49", "81"], 3),

    ("Beacon beam qaysi blokdan o'ta olmaydi?",
     ["Glass", "Bedrock", "Water", "Leaves"], 1),

    ("Nether Star qaysi mobdan tushadi?",
     ["Wither", "Warden", "Ghast", "Ender Dragon"], 0),

    ("Wither qaysi HP chegarasida yangi hujum bosqichiga o'tadi?",
     ["75%", "25%", "50%", "10%"], 2),

    ("Wither ikkinchi bosqichda qanday hujumga ega bo'ladi?",
     ["Uchadi", "Teleport qiladi", "Armor oladi", "Invisible bo'ladi"], 2),

    ("Ender Dragonni qayta chaqirish uchun nechta End Crystal kerak?",
     ["2", "6", "8", "4"], 3),

    ("End Crystal qaysi blok ustiga qo'yilishi mumkin?",
     ["Obsidian yoki Bedrock", "Stone", "Iron Block", "End Stone"], 0),

    ("Dragon Egg odatda Ender Dragon mag'lub bo'lgandan keyin qayerda paydo bo'ladi?",
     ["End City", "Exit Portal", "Stronghold", "Spawn Point"], 1),

    ("End Gateway qanday usul bilan ochilishi mumkin?",
     ["Wither chaqirish", "100 ta Enderman o'ldirish", "Ender Dragonni qayta chaqirish va mag'lub qilish", "Beacon qurish"], 2),

    ("End City ko'pincha qaysi biome'da joylashadi?",
     ["The End", "End Highlands", "End Midlands", "Void"], 1),

    ("Elytra qayerdan topiladi?",
     ["Stronghold", "Nether Fortress", "End City Ship", "Ancient City"], 2),

    ("Elytra bilan uchishda qaysi item tezlikni oshiradi?",
     ["Arrow", "Firework Rocket", "Snowball", "Ender Pearl"], 1),

    ("Shulker Box'ning eng muhim xususiyati nima?",
     ["Cheksiz item beradi", "Ichidagi itemlar blok sindirilganda saqlanadi", "O'z-o'zidan ochiladi", "Redstone generator"], 1),

    ("Shulker qaysi effektni beradi?",
     ["Slow Falling", "Levitation", "Glowing", "Weakness"], 1),

    ("Shulker projectile blokka urilganda nima bo'lishi mumkin?",
     ["Levitation beradi", "Burns", "Explode qiladi", "Teleport qiladi"], 0),

    ("Ancient City qaysi biome'da hosil bo'ladi?",
     ["Lush Cave", "Dripstone Cave", "Deep Dark", "Deep Ocean"], 2),

    ("Ancient City'dagi eng xavfli mob qaysi?",
     ["Ravager", "Warden", "Evoker", "Wither"], 1),

    ("Trial Chamber qaysi yangi jangovar tizim bilan bog'liq?",
     ["Trial Spawner", "Raid Captain", "Dragon Egg", "Beacon"], 0),

    ("Breeze asosan qaysi joyda uchraydi?",
     ["Ancient City", "Trial Chamber", "Nether Fortress", "Stronghold"], 1),

    ("Breeze'ning asosiy projectile'i nima deb ataladi?",
     ["Wind Ball", "Air Shot", "Wind Charge", "Gust Orb"], 2),

    ("Wind Charge nima qila oladi?",
     ["Suvni muzlatadi", "Nether portal ochadi", "O'yinchini yoki entityni knockback qiladi", "Moblarni heal qiladi"], 2),

    ("Mace uchun Density enchantmenti nimani kuchaytiradi?",
     ["Mining speed", "Falling attack damage", "Movement speed", "Durability"], 1),

    ("Mace uchun Breach enchantmenti nimaga qarshi foydali?",
     ["Fire", "Armor", "Potions", "Shields"], 1),

    ("Mace uchun Wind Burst nimaga imkon beradi?",
     ["Suvda tez yuradi", "Teleport qiladi", "Smash hujumidan keyin o'yinchini yuqoriga qaytaradi", "Invisible qiladi"], 2),

    ("Minecraft Java'da Critical Hit qachon bajariladi?",
     ["Sprint qilganda", "O'yinchi havoda tushayotgan paytda hujum qilsa", "Sneak qilganda", "Suvda turganda"], 1),

    ("Critical Hit qaysi holatda bajarilmaydi?",
     ["O'yinchi yiqilayotganda", "Jumpdan tushayotganda", "O'yinchi to'liq yerda turganda", "Fall bilan hujum qilganda"], 2),

    ("Sweeping Edge enchantmenti nimani kuchaytiradi?",
     ["Sweep attack", "Critical damage", "Bow damage", "Fire damage"], 0),

    ("Looting enchantmentining asosiy vazifasi nima?",
     ["XPni ikki baravar qilish", "Mob drop miqdorini oshirish", "Weapon durabilityni oshirish", "Armorni kuchaytirish"], 1),

    ("Fortune enchantmenti qaysi turdagi bloklardan ko'proq drop olishga yordam beradi?",
     ["Obsidian", "Certain ores/crops", "Bedrock", "End Portal"], 1),

    ("Silk Touch bilan qaysi blokni olish mumkin?",
     ["Bedrock", "End Portal Frame", "Glass", "Spawner"], 2),

    ("Silk Touch bilan Spawnerni odatiy survival'da olish mumkinmi?",
     ["Ha", "Yo'q", "Faqat Netherda", "Faqat Endda"], 1),

    ("Mending enchantmenti itemni qanday tiklaydi?",
     ["Coal orqali", "XP orqali", "Iron orqali", "Food orqali"], 1),

    ("Unbreaking enchantmenti nima qiladi?",
     ["Damage ikki baravar bo'ladi", "Item durability kamayish ehtimolini pasaytiradi", "XP oshadi", "Speed oshadi"], 1),

    ("Infinity enchantmenti qaysi item uchun mashhur?",
     ["Sword", "Shield", "Bow", "Pickaxe"], 2),

    ("Infinity va Mending bir bow'da Java Edition'da odatiy enchantment sifatida birga qo'yiladimi?",
     ["Ha", "Faqat Netherda", "Yo'q", "Faqat Creative'da"], 2),

    ("Riptide enchantmenti qachon ishlaydi?",
     ["Faqat Netherda", "Suvda yoki yomg'irda", "Faqat quruqlikda", "Faqat Endda"], 1),

    ("Channeling enchantmenti nima qilishi mumkin?",
     ["Suv yaratadi", "Mobni freeze qiladi", "Momaqaldiroq paytida lightning chaqirishi mumkin", "Teleport qiladi"], 2),

    ("Loyalty enchantmenti qaysi qurolga tegishli?",
     ["Trident", "Mace", "Bow", "Crossbow"], 0),

    ("Soul Speed qaysi bloklarda tezlik beradi?",
     ["Ice", "Soul Sand va Soul Soil", "Stone", "End Stone"], 1),

    ("Frost Walker enchantmenti nima qiladi?",
     ["Lava ustida yuradi", "Yomg'irni to'xtatadi", "Suv ustida muz hosil qiladi", "Snowball beradi"], 2),

    ("Depth Strider nimani tezlashtiradi?",
     ["Yugurishni", "Suvdagi harakatni", "Flyingni", "Miningni"], 1),

    ("Aqua Affinity nimani tezlashtiradi?",
     ["Suv ostidagi mining", "Suvda yurish", "Fishing", "Swimming damage"], 0),

    ("Respiration enchantmenti nima beradi?",
     ["Ko'proq damage", "Suv ostida uzoqroq nafas olish", "Tezroq yugurish", "Night Vision"], 1),

    ("Totem of Undying qaysi mobdan tushadi?",
     ["Vindicator", "Pillager", "Evoker", "Ravager"], 2),

    ("Evoker qaysi hujumdan foydalanadi?",
     ["Fangs", "Fireball", "Wind Charge", "Dragon Breath"], 0),

    ("Totem ishlaganda o'yinchiga qaysi effektlardan biri beriladi?",
     ["Haste", "Regeneration", "Mining Fatigue", "Glowing only"], 1),

    ("Raid'ni boshlash uchun odatda qaysi effekt kerak?",
     ["Hero of the Village", "Bad Omen", "Darkness", "Ominous"], 1),

    ("Raid tugagandan keyin qaysi effekt beriladi?",
     ["Bad Omen", "Glowing", "Hero of the Village", "Strength"], 2),

    ("Hero of the Village nima beradi?",
     ["Permanent Strength", "Night Vision", "Village savdolarida chegirmalar va bonuslar", "Flying"], 2),

    ("Ravager qaysi event bilan bog'liq?",
     ["Trial", "Raid", "End", "Nether"], 1),

    ("Pillager Outpost'da qaysi mob ko'p uchraydi?",
     ["Pillager", "Evoker", "Warden", "Piglin Brute"], 0),

    ("Piglin Brute qayerda uchraydi?",
     ["Nether Fortress", "Bastion Remnant", "Stronghold", "End City"], 1),

    ("Piglin qaysi itemni kiygan o'yinchiga odatda hujum qilmaydi?",
     ["Diamond armor", "Iron armor", "Gold armor", "Netherite armor"], 2),

    ("Piglin bilan barter qilish uchun nima kerak?",
     ["Gold Ingot", "Gold Nugget", "Emerald", "Diamond"], 0),

    ("Piglin barterida qaysi item juda foydali?",
     ["Diamond", "Ender Pearl", "Elytra", "Nether Star"], 1),

    ("Netherite upgrade template qayerdan topiladi?",
     ["Bastion Remnant", "Nether Fortress", "Stronghold", "Village"], 0),

    ("Netherite upgrade qilishda diamond gear ustiga nima qo'shiladi?",
     ["Netherite Scrap", "Ancient Debris", "Netherite Ingot", "Gold Block"], 2),

    ("Ancient Debris qaysi o'lchamda topiladi?",
     ["Overworld", "Nether", "End", "Deep Dark"], 1),

    ("Ancient Debris qaysi blok bilan portlashga chidamli?",
     ["Glass", "Dirt", "Obsidian darajasiga yaqin", "Wood"], 2),

    ("Netherite itemlar lava ichida nima qiladi?",
     ["Darhol yo'qoladi", "Suzib turadi", "Yonadi", "Obsidian bo'ladi"], 1),

    ("Nether Fortress'da qaysi mobning spawneri uchraydi?",
     ["Warden", "Blaze", "Shulker", "Breeze"], 1),

    ("Blaze Rod qaysi mobdan tushadi?",
     ["Ghast", "Blaze", "Magma Cube", "Wither Skeleton"], 1),

    ("Blaze Powder nimani tayyorlashda kerak?",
     ["End Crystal", "Beacon", "Eye of Ender", "Elytra"], 2),

    ("Eye of Ender qaysi ikki asosiy itemdan tayyorlanadi?",
     ["Ender Pearl + Ghast Tear", "Ender Pearl + Blaze Powder", "Blaze Rod + Diamond", "Obsidian + Blaze Powder"], 1),

    ("Strongholdni topishda qaysi item yordam beradi?",
     ["Compass", "Eye of Ender", "Recovery Compass", "Spyglass"], 1),

    ("End Portal Frame'ni Survival'da oddiy usulda olish mumkinmi?",
     ["Yo'q", "Ha", "Faqat Fortune bilan", "Faqat Silk Touch bilan"], 0),

    ("End Portal odatda qayerda joylashadi?",
     ["End City", "Stronghold", "Ancient City", "Bastion"], 1),

    ("Compass qaysi joyda odatda foydasiz yo'nalish ko'rsatishi mumkin?",
     ["Overworld", "Village", "Nether", "Ocean"], 2),

    ("Lodestone Compass nimaga bog'lanadi?",
     ["Beacon", "Lodestone", "Respawn Anchor", "End Portal"], 1),

    ("Recovery Compass nimani ko'rsatadi?",
     ["Oxirgi o'lim joyini", "Spawn pointni", "Strongholdni", "Village'ni"], 0),

    ("Recovery Compass qaysi materialni talab qiladi?",
     ["Amethyst Shard", "Prismarine", "Echo Shard", "Quartz"], 2),

    ("Echo Shard qayerdan topiladi?",
     ["End City", "Ancient City", "Stronghold", "Bastion"], 1),

    ("Conduit qanday bloklar bilan quriladi?",
     ["Obsidian", "Iron Block", "Prismarine/Sea Lantern bloklari", "Copper Block"], 2),

    ("Conduit suv ostida qanday bonus beradi?",
     ["Conduit Power", "Haste", "Strength", "Fire Resistance"], 0),

    ("Tridentni oddiy crafting table'da craft qilish mumkinmi?",
     ["Ha", "Yo'q", "Faqat Netherda", "Faqat Endda"], 1),

    ("Trident asosan qaysi mobdan olinadi?",
     ["Guardian", "Drowned", "Elder Guardian", "Zombie"], 1),

    ("Elder Guardian o'yinchiga qaysi effektni beradi?",
     ["Darkness", "Weakness", "Mining Fatigue", "Slowness"], 2),

    ("Ocean Monumentning asosiy guardian moblaridan biri qaysi?",
     ["Warden", "Elder Guardian", "Evoker", "Shulker"], 1),

    ("Guardian qaysi attackdan foydalanadi?",
     ["Laser", "Arrow", "Fireball", "Wind Charge"], 0),

    ("Dolphin's Grace effekti Java Edition'da qanday olinadi?",
     ["Dolphinni o'ldirish orqali", "Dolphin yaqinida suzish orqali", "Fish berish orqali", "Potion orqali"], 1),

    ("Turtle Shell qaysi helmet effektini beradi?",
     ["Night Vision", "Conduit Power", "Water Breathing", "Dolphin's Grace"], 2),

    ("Turtle Scute qayerdan olinadi?",
     ["Turtle o'lganda", "Baby turtle ulg'ayganda", "Fishingdan", "Ocean Monumentdan"], 1),

    ("Villager zombiga aylantirilib yana davolansa nima bo'lishi mumkin?",
     ["XP yo'qoladi", "Savdo narxlari pasayadi", "Village yo'qoladi", "Villager teleport qiladi"], 1),

    ("Zombie Villager'ni davolash uchun nima kerak?",
     ["Strength + Apple", "Weakness + Golden Apple", "Regeneration + Gold", "Potion of Healing + Emerald"], 1),

    ("Villager qaysi blok orqali Librarian kasbini oladi?",
     ["Bookshelf", "Cartography Table", "Lectern", "Stonecutter"], 2),

    ("Villager qaysi blok orqali Armorer bo'ladi?",
     ["Blast Furnace", "Smithing Table", "Anvil", "Furnace"], 0),

    ("Villager qaysi blok orqali Toolsmith bo'ladi?",
     ["Grindstone", "Smithing Table", "Stonecutter", "Anvil"], 1),

    ("Villager qaysi blok orqali Weaponsmith bo'ladi?",
     ["Grindstone", "Smithing Table", "Anvil", "Blast Furnace"], 0),

    ("Java Edition'da villager trade'larini yangilashning asosiy usuli nima?",
     ["Uni urish", "Workstation bilan ishlash", "Uni boqish", "Uni uxlatmaslik"], 1),

    ("Redstone signalining oddiy maksimal kuchi nechaga teng?",
     ["10", "20", "15", "255"], 2),

    ("Redstone repeater signalni necha blokdan keyin qayta kuchaytiradi?",
     ["15 blok", "10 blok", "20 blok", "5 blok"], 0),

    ("Comparator qaysi maxsus vazifani bajarishi mumkin?",
     ["Faqat piston boshqarish", "Container signalini o'qish", "Faqat lampani yoqish", "Faqat eshik ochish"], 1),

    ("Hopper itemlarni qaysi yo'nalishda uzatishi mumkin?",
     ["Faqat yuqoriga", "Faqat pastga", "Yuqoridan pastga va yon tomondan", "Faqat diagonal"], 2),

    ("Observer nimani aniqlaydi?",
     ["Faqat moblarni", "Block state change", "Faqat itemlarni", "Faqat yorug'likni"], 1),

    ("Piston qaysi blokni odatda siljita olmaydi?",
     ["Stone", "Dirt", "Obsidian", "Glass"], 2),

    ("Sticky Pistonning oddiy pistondan asosiy farqi nima?",
     ["Tezroq ishlaydi", "Blokni qaytarib torta oladi", "Ko'proq blok itaradi", "Redstone talab qilmaydi"], 1),

    ("Minecraft Java'da hopper orqali nechta item bir vaqtning o'zida o'tadi?",
     ["5", "1", "16", "64"], 1)
]


def quiz_keyboard(options):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    str(options[0]), callback_data="quiz_answer:0"),
                InlineKeyboardButton(
                    str(options[1]), callback_data="quiz_answer:1"),
            ],
            [
                InlineKeyboardButton(
                    str(options[2]), callback_data="quiz_answer:2"),
                InlineKeyboardButton(
                    str(options[3]), callback_data="quiz_answer:3"),
            ],
        ]
    )

# ================================================================
# /QUIZ
# ================================================================


async def quiz_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    chat_id = update.effective_chat.id

    active = db.execute(
        """
        SELECT *
        FROM quizzes
        WHERE chat_id = ?
          AND active = 1
        LIMIT 1
        """,
        (chat_id,),
    ).fetchone()

    if active:
        await send_temporary(
            update,
            context,
            "🧠 Bu chatda allaqachon quiz bor.\n"
            "Kimdir javob bersin.",
        )
        schedule_delete_command(
            update,
            context,
        )
        return

    question, options, correct = random.choice(
        QUIZ_DATA
    )

    message = await update.effective_chat.send_message(
        f"🧠 <b>MINECRAFT QUIZ!</b>\n\n"
        f"{html.escape(question)}\n\n"
        "👇 Javobni tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=quiz_keyboard(options),
    )

    db.execute(
        """
        INSERT INTO quizzes
        (
            chat_id,
            question,
            options,
            correct,
            message_id,
            creator_id,
            creator_message_id,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            chat_id,
            question,
            "|".join(options),
            correct,
            message.message_id,
            update.effective_user.id,
            update.message.message_id if update.message else 0,
            now(),
        ),
    )

    db.commit()
    # If nobody answers, the quiz stays visible.


# ================================================================
# QUIZ ANSWER
# ================================================================

async def quiz_answer_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    selected: int,
):
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    quiz = db.execute(
        """
        SELECT *
        FROM quizzes
        WHERE chat_id = ?
          AND message_id = ?
          AND active = 1
        LIMIT 1
        """,
        (
            chat_id,
            message_id,
        ),
    ).fetchone()

    if quiz is None:
        await query.answer(
            "⌛ Quiz tugagan.",
            show_alert=True,
        )
        return

    db.execute(
        """
        UPDATE quizzes
        SET active = 0
        WHERE id = ?
        """,
        (quiz["id"],),
    )

    db.commit()

    if selected == quiz["correct"]:
        change_xp(
            query.from_user.id,
            100,
        )

        change_coins(
            query.from_user.id,
            100,
        )

        result = (
            "🎉 <b>TO‘G‘RI JAVOB!</b>\n\n"
            f"👤 {display_name(query.from_user.id)}\n"
            "⭐ +100 XP\n"
            "💰 +100 Coins"
        )
    else:
        result = (
            "❌ <b>NOTO‘G‘RI JAVOB</b>\n\n"
            f"👤 {display_name(query.from_user.id)}"
        )

    try:
        await query.message.edit_text(
            result,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    schedule_delete(
        context.bot,
        chat_id,
        message_id,
        10,
    )

    creator_message_id = int(quiz["creator_message_id"] or 0)
    if creator_message_id and creator_message_id != message_id:
        schedule_delete(
            context.bot,
            chat_id,
            creator_message_id,
            10,
        )

    await query.answer(
        "Javob qabul qilindi.",
    )


# ================================================================
# /PAY
# ================================================================

async def pay_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    if len(context.args) < 2:
        await send_temporary(
            update,
            context,
            "❌ <code>/pay @username summa</code>",
        )
        schedule_delete_command(update, context)
        return

    target_name = context.args[0]
    target_name = target_name.lstrip("@")

    try:
        amount = int(context.args[1])
    except ValueError:
        amount = 0

    if amount <= 0:
        await send_temporary(
            update,
            context,
            "❌ Summa noto‘g‘ri.",
        )
        schedule_delete_command(update, context)
        return

    target = get_user_by_username(
        target_name
    )

    if target is None:
        await send_temporary(
            update,
            context,
            "❌ Player topilmadi.",
        )
        schedule_delete_command(update, context)
        return

    sender_id = update.effective_user.id

    if target["id"] == sender_id:
        await send_temporary(
            update,
            context,
            "❌ O‘zingizga coin yubora olmaysiz.",
        )
        schedule_delete_command(update, context)
        return

    if get_coins(sender_id) < amount:
        await send_temporary(
            update,
            context,
            "❌ Coin yetarli emas.",
        )
        schedule_delete_command(update, context)
        return

    change_coins(
        sender_id,
        -amount,
    )

    change_coins(
        target["id"],
        amount,
    )

    await send_temporary(
        update,
        context,
        f"💰 <b>PAY</b>\n\n"
        f"👤 {display_name(sender_id)} → "
        f"{display_name(target['id'])}\n"
        f"💰 {amount} coin",
    )

    schedule_delete_command(
        update,
        context,
    )


# ================================================================
# ADMIN /GIVE TARGET PARSER
# ================================================================

def parse_give_arguments(args):
    if len(args) < 3:
        return None, None, None

    target = args[0]
    item = args[1].lower()

    try:
        amount = int(args[2])
    except ValueError:
        return target, item, None

    return target, item, amount


# ================================================================
# ADMIN /GIVE
# ================================================================

async def give_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    if not is_admin(
        update.effective_user.id
    ):
        await send_temporary(
            update,
            context,
            "❌ <b>ADMIN ONLY</b>",
        )
        schedule_delete_command(update, context)
        return

    target_name, item, amount = parse_give_arguments(
        context.args
    )

    if target_name is None:
        await send_temporary(
            update,
            context,
            "❌ Foydalanish:\n"
            "<code>/give @nik item nomi soni</code>\n\n"
            "Masalan:\n"
            "<code>/give @player strength 3</code>\n"
            "<code>/give @player xp 1000</code>\n"
            "<code>/give @player pay 5000</code>",
        )
        schedule_delete_command(
            update,
            context,
        )
        return

    if amount is None or amount <= 0:
        await send_temporary(
            update,
            context,
            "❌ Son noto‘g‘ri.",
        )
        schedule_delete_command(
            update,
            context,
        )
        return

    target_name = target_name.lstrip("@")

    target = get_user_by_username(
        target_name
    )

    if target is None:
        await send_temporary(
            update,
            context,
            "❌ Player topilmadi.",
        )
        schedule_delete_command(
            update,
            context,
        )
        return

    # XP is an admin resource.
    if item == "xp":
        change_xp(
            target["id"],
            amount,
        )

        result = f"⭐ {amount} XP"

    # Coins can be called pay/coins.
    elif item in (
        "pay",
        "coins",
        "coin",
    ):
        change_coins(
            target["id"],
            amount,
        )

        result = f"💰 {amount} Coins"

    # All shop items.
    elif item in ITEMS:
        add_item(
            target["id"],
            item,
            amount,
        )

        result = (
            f"{ITEMS[item]['name']} ×{amount}"
        )

    else:
        await send_temporary(
            update,
            context,
            "❌ <b>Noto‘g‘ri item.</b>\n\n"
            "Mavjud itemlar:\n"
            "xp\n"
            "coins\n"
            "hp\n"
            "strength\n"
            "shield\n"
            "duel_ticket\n"
            "mystery_box",
        )

        schedule_delete_command(
            update,
            context,
        )
        return

    message = await update.effective_chat.send_message(
        f"✅ <b>ITEM BERILDI</b>\n\n"
        f"👤 {display_name(target['id'])}\n"
        f"🎁 {result}",
        parse_mode=ParseMode.HTML,
    )

    # Give confirmation itself disappears in 10 seconds.
    schedule_delete(
        context.bot,
        message.chat_id,
        message.message_id,
        10,
    )

    # /give command also disappears in 10 seconds.
    schedule_delete_command(
        update,
        context,
        10,
    )


# ================================================================
# ADMIN /ADMIN
# ================================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    ensure_user(update.effective_user)

    if not is_admin(
        update.effective_user.id
    ):
        await send_temporary(
            update,
            context,
            "❌ Faqat admin.",
        )
        schedule_delete_command(update, context)
        return

    active = get_active_boss()

    text = (
        "🔐 <b>ADMIN PANEL</b>\n\n"
        "🎁 /give @nik item soni\n"
        "👹 /spawn boss\n"
        "👑 /doncarlo\n\n"
        f"👹 Active boss: "
        f"{html.escape(active['name']) if active else 'Yo‘q'}"
    )

    await send_temporary(
        update,
        context,
        text,
        seconds=20,
    )

    schedule_delete_command(
        update,
        context,
        20,
    )


# ================================================================
# CALLBACK ROUTER
# ================================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data or ""

    # ------------------------------------------------------------
    # SHOP
    # ------------------------------------------------------------

    if data.startswith("shop:"):
        item = data.split(
            ":",
            1,
        )[1]

        await shop_callback(
            query,
            context,
            item,
        )

        return

    # ------------------------------------------------------------
    # DUEL ACCEPT
    # ------------------------------------------------------------

    if data.startswith("duel_accept:"):
        parts = data.split(":")

        if len(parts) != 3:
            return

        challenger = int(parts[1])
        target = int(parts[2])

        await duel_accept_callback(
            query,
            context,
            challenger,
            target,
        )

        return

    # ------------------------------------------------------------
    # DUEL DECLINE
    # ------------------------------------------------------------

    if data.startswith("duel_decline:"):
        parts = data.split(":")

        if len(parts) != 3:
            return

        challenger = int(parts[1])
        target = int(parts[2])

        await duel_decline_callback(
            query,
            context,
            challenger,
            target,
        )

        return

    # ------------------------------------------------------------
    # DUEL ATTACK
    # ------------------------------------------------------------

    if data.startswith("duel_attack:"):
        duel_id = int(
            data.split(
                ":",
                1,
            )[1]
        )

        await perform_duel_attack(
            query,
            context,
            duel_id,
            query.from_user.id,
        )

        return

    # ------------------------------------------------------------
    # DUEL STRENGTH
    # ------------------------------------------------------------

    if data.startswith("duel_strength:"):
        duel_id = int(
            data.split(
                ":",
                1,
            )[1]
        )

        await perform_strength(
            query,
            context,
            duel_id,
            query.from_user.id,
        )

        return

    # ------------------------------------------------------------
    # DUEL HP
    # ------------------------------------------------------------

    if data.startswith("duel_hp:"):
        duel_id = int(
            data.split(
                ":",
                1,
            )[1]
        )

        await perform_hp(
            query,
            context,
            duel_id,
            query.from_user.id,
        )

        return

    # ------------------------------------------------------------
    # DUEL SHIELD
    # ------------------------------------------------------------

    if data.startswith("duel_shield:"):
        duel_id = int(
            data.split(
                ":",
                1,
            )[1]
        )

        await perform_shield(
            query,
            context,
            duel_id,
            query.from_user.id,
        )

        return

    # ------------------------------------------------------------
    # DUEL FORFEIT
    # ------------------------------------------------------------

    if data.startswith("duel_forfeit:"):
        duel_id = int(
            data.split(
                ":",
                1,
            )[1]
        )

        await perform_forfeit(
            query,
            context,
            duel_id,
            query.from_user.id,
        )

        return

    # ------------------------------------------------------------
    # QUIZ ANSWER
    # ------------------------------------------------------------

    if data.startswith("quiz_answer:"):
        selected = int(
            data.split(
                ":",
                1,
            )[1]
        )

        await quiz_answer_callback(
            query,
            context,
            selected,
        )

        return


# ================================================================
# UNKNOWN COMMAND
# ================================================================

async def unknown_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await send_temporary(
        update,
        context,
        "❌ Noma’lum command.\n"
        "📚 /help",
    )

    schedule_delete_command(
        update,
        context,
    )


# ================================================================
# ERROR HANDLER
# ================================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    # Do not send technical errors into group chats.
    # Print them to console for debugging.
    print(
        "BOT ERROR:",
        repr(context.error),
    )


# ================================================================
# APPLICATION SETUP
# ================================================================

def build_application():
    if (
        not BOT_TOKEN
        or BOT_TOKEN.startswith(
            "PASTE_YOUR"
        )
    ):
        raise RuntimeError(
            "BOT_TOKEN ni bot.py ichida yozing."
        )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ------------------------------------------------------------
    # PUBLIC COMMANDS
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "profile",
            profile,
        )
    )

    application.add_handler(
        CommandHandler(
            "ranks",
            ranks,
        )
    )

    application.add_handler(
        CommandHandler(
            "top",
            top,
        )
    )

    application.add_handler(
        CommandHandler(
            "shop",
            shop,
        )
    )

    application.add_handler(
        CommandHandler(
            "inventory",
            inventory,
        )
    )

    application.add_handler(
        CommandHandler(
            "buy",
            buy,
        )
    )

    application.add_handler(
        CommandHandler(
            "openbox",
            openbox,
        )
    )

    # ------------------------------------------------------------
    # DUEL COMMANDS
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "duel",
            duel_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "attack",
            attack_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "potion",
            potion_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "hp",
            hp_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "shield",
            shield_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "forfeit",
            forfeit_command,
        )
    )

    # ------------------------------------------------------------
    # BOSS COMMANDS
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "boss",
            boss_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "bossattack",
            boss_attack_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "spawn",
            spawn_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "doncarlo",
            doncarlo_command,
        )
    )

    # /boss_top
    application.add_handler(
        CommandHandler(
            "bosstop",
            boss_top_command,
        )
    )

    # ------------------------------------------------------------
    # QUIZ
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "quiz",
            quiz_command,
        )
    )

    # ------------------------------------------------------------
    # ECONOMY
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "pay",
            pay_command,
        )
    )

    # ------------------------------------------------------------
    # ADMIN
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "give",
            give_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    # ------------------------------------------------------------
    # BUTTONS
    # ------------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    return application


# ================================================================
# MAIN
# ================================================================

def main():
    init_database()

    print(
        "================================================"
    )
    print(
        "⚡ MINECRAFT COMMUNITY SYSTEM STARTED"
    )
    print(
        "================================================"
    )
    print(
        "Database:",
        DB_PATH,
    )
    print(
        "Ranks:",
        len(RANKS),
    )
    print(
        "Bosses:",
        len(BOSSES),
    )
    print(
        "Items:",
        len(ITEMS),
    )
    print(
        "Duel attack cooldown:",
        DUEL_ATTACK_COOLDOWN,
        "seconds",
    )
    print(
        "Boss attack cooldown:",
        BOSS_ATTACK_COOLDOWN,
        "seconds",
    )

    application = build_application()

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

# ================================================================
# COMMAND REFERENCE
# ================================================================
# /start — botni boshlaydi
# /help — komandalarni ko‘rsatadi
# /profile — profil
# /ranks — ranklar
# /top — XP bo‘yicha TOP
# /shop — item shop
# /buy ITEM — item sotib olish
# /inventory — inventory
# /openbox — Mystery Box ochish
# /duel @username — duel challenge
# /attack — duel attack
# /potion strength — Strength Potion
# /hp — HP Potion
# /shield — Shield
# /forfeit — duelni tugatish
# /boss — faol boss
# /bossattack — bossga zarba
# /bosstop — boss damage TOP
# /quiz — Minecraft quiz
# /pay @username SUMMA — coin yuborish
# /spawn BOSS — admin boss spawn
# /doncarlo — admin DONCARLO spawn
# /give @username ITEM SONI — admin give
# /admin — admin panel

# ================================================================
# ITEM REFERENCE
# ================================================================
# xp — XP Potion
# hp — HP Potion
# duel_ticket — Duel Ticket
# mystery_box — Mystery Box
# shield — Shield
# strength — Strength Potion

# ================================================================
# DUEL RULES
# ================================================================
# Duel boshlash uchun challengerda Duel Ticket bo‘lishi kerak.
# Duel attack cooldown 3 sekund.
# Strength bir duelda 1 marta.
# Strength 30 sekund davomida damage x1.5.
# HP Potion bir duelda 5 marta.
# HP Potion maksimal HPning 20 foizini tiklaydi.
# Shield bir duelda 2 marta.
# Shield keyingi damage'ni 50 foiz kamaytiradi.
# Shield urilgandan keyin o‘chadi.
# Navbat item ishlatilganda raqibga o‘tadi.
# Yutgan player coin va XP oladi.
# Yutqazgan player coin va XP yo‘qotadi.
# Taslim bo‘lish ham mag‘lubiyat hisoblanadi.

# ================================================================
# BOSS RULES
# ================================================================
# Boss attack cooldown 2 sekund.
# Boss damage player rank damage asosida hisoblanadi.
# Boss HP tugaganda Top Damage aniqlanadi.
# 1-o‘rin eng katta reward oladi.
# 2-o‘rin 75 foiz reward oladi.
# 3-o‘rin 55 foiz reward oladi.
# 4-o‘rin 35 foiz reward oladi.
# 5-o‘rin 25 foiz reward oladi.
# Qolgan damage berganlar 10 foiz reward oladi.
# DONCARLO eng kuchli boss.

# ================================================================
# RANK RULES
# ================================================================
# XP oshishi bilan rank oshadi.
# Rank oshishi bilan HP oshadi.
# Rank oshishi bilan base damage oshadi.
# Emperor 2000 HP bilan tugaydi.
# Ranklar jami 10 ta.

# ================================================================
# MAINTENANCE NOTES
# ================================================================
# 001. SQLite database persists user profiles.
# 002. SQLite database persists inventory.
# 003. SQLite database persists boss HP.
# 004. SQLite database persists boss damage.
# 005. SQLite database persists duel state.
# 006. SQLite database persists duel item usage counts.
# 007. Quiz state is stored per chat.
# 008. Temporary messages use asyncio tasks.
# 009. Admin permissions use Telegram numeric IDs.
# 010. Username matching is case-insensitive.
# 011. Coins can never fall below zero.
# 012. XP can never fall below zero.
# 013. Boss HP cannot become negative.
# 014. Duel HP cannot become negative.
# 015. Damage is randomized around rank damage.
# 016. Boss damage is capped by remaining boss HP.
# 017. A user cannot duel themselves.
# 018. A player cannot enter two active duels.
# 019. A target already in a duel cannot accept another.
# 020. A duel ticket is consumed when a duel starts.
# 021. Strength is checked server-side.
# 022. HP usage is checked server-side.
# 023. Shield usage is checked server-side.
# 024. Duel turn is checked server-side.
# 025. Attack cooldown is checked server-side.
# 026. Boss cooldown is checked server-side.
# 027. Wrong shop item is rejected.
# 028. Wrong admin item is rejected.
# 029. Wrong boss name is rejected.
# 030. Unknown command gets a temporary error.
# 031. Quiz accepts the first valid answer.
# 032. Quiz result is deleted after ten seconds.
# 033. Quiz creator command is deleted.
# 034. Give confirmation is deleted after ten seconds.
# 035. Give command is deleted after ten seconds.
# 036. Boss attack result is deleted after ten seconds.
# 037. Boss defeat summary remains temporarily.
# 038. Duel result is temporary.
# 039. Shop buttons are callback-based.
# 040. Duel buttons are callback-based.
# 041. Quiz buttons are callback-based.
# 042. Callback users are verified where ownership matters.
# 043. Duel challenge target is verified before acceptance.
# 044. Duel forfeit checks ownership.
# 045. Inventory amounts cannot be negative through remove_item.
# 046. Mystery Box is consumed before reward generation.
# 047. Mystery Box rewards are randomized.
# 048. Profile shows current rank HP.
# 049. Profile shows current base damage.
# 050. Profile shows XP.
# 051. Profile shows coins.
# 052. Profile shows wins.
# 053. Profile shows losses.
# 054. Profile shows total damage.
# 055. Top list sorts by XP first.
# 056. Boss Top sorts by damage.
# 057. Boss reward depends on placement.
# 058. DONCARLO alias is accepted.
# 059. DONCARLETTO alias is accepted for compatibility.
# 060. The display name is DONCARLO.
# 061. The old boss chest concept is not used.
# 062. The bot is intended for group chats.
# 063. The bot can also answer in private chat.
# 064. HTML escaping is used for user names in messages.
# 065. The database uses WAL mode.
# 066. The application uses python-telegram-bot.
# 067. The bot uses async handlers.
# 068. The polling loop runs continuously.
# 069. drop_pending_updates prevents old command replay.

# ================================================================
# DUEL ENGINE
# ================================================================
# Maintenance pass 1:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.
# Maintenance pass 2:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.
# Maintenance pass 3:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.
# Maintenance pass 4:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.
# Maintenance pass 5:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.
# Maintenance pass 6:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.
# Maintenance pass 7:
#   Duel state lives in the duels table.
#   Player one is stored as player1.
#   Player two is stored as player2.
#   HP for player one is stored in hp1.
#   HP for player two is stored in hp2.
#   Maximum HP is stored independently.
#   Turn is stored as Telegram user ID.
#   Active duel status is exactly the string active.
#   Finished duel status is finished.
#   Forfeit uses the same finished status.
#   Winner and loser IDs are saved.
#   Creation timestamp is saved.
#   Finish timestamp is saved.
#   Duel stats have one row per player.
#   HP uses are counted in duel_stats.
#   Shield uses are counted in duel_stats.
#   Strength uses are counted in duel_stats.
#   Strength expiry is stored as Unix time.
#   Shield state is stored as integer 0 or 1.
#   Attack checks turn before damage.
#   Attack checks cooldown before damage.
#   Attack checks player membership before damage.
#   Defender shield is checked before applying damage.
#   Damage is recorded in total_damage.
#   A zero HP defender ends the duel.
#   Rewards are granted once at finish.
#   The finish function changes status before rewards.

# ================================================================
# BOSS ENGINE
# ================================================================
# Maintenance pass 1:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.
# Maintenance pass 2:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.
# Maintenance pass 3:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.
# Maintenance pass 4:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.
# Maintenance pass 5:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.
# Maintenance pass 6:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.
# Maintenance pass 7:
#   Only one active boss is allowed by command logic.
#   Boss config is held in BOSSES.
#   Boss aliases are held in BOSS_ALIASES.
#   Boss HP is persistent.
#   Boss damage is persistent.
#   Boss Top uses accumulated damage.
#   The boss is defeated when HP reaches zero.
#   Boss reward uses the configured reward pool.
#   Placement multiplier is applied per player.
#   Top five receive stronger rewards.
#   Players outside top five still receive a smaller reward.
#   The boss is deactivated after defeat.
#   Boss HP is reset through spawn.
#   Boss damage is cleared on a new spawn.
#   DONCARLO has 10000 HP.
#   DONCARLO has the largest configured reward pool.
#   DONCARLO has the highest configured damage range.
#   The command name is /doncarlo.
#   The admin shortcut calls the same spawn engine.

# ================================================================
# SHOP ENGINE
# ================================================================
# Maintenance pass 1:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
# Maintenance pass 2:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
# Maintenance pass 3:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
# Maintenance pass 4:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
# Maintenance pass 5:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
# Maintenance pass 6:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
# Maintenance pass 7:
#   All purchasable items are defined in ITEMS.
#   Every item has a display name.
#   Every item has a price.
#   Every item has a description.
#   Shop purchases check the coin balance.
#   Shop purchases subtract coins before adding the item.
#   Shop buttons use callback data.
#   Direct /buy also works.
#   Invalid items are rejected.
#   Inventory stores item amounts.
#   Inventory rows are created on first purchase.
#   Inventory can be displayed with /inventory.
#   Mystery Box is a normal inventory item.
#   Duel Ticket is a normal inventory item.
#   Strength is a normal inventory item.
#   HP Potion is a normal inventory item.
#   Shield is a normal inventory item.
