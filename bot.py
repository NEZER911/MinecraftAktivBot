import sqlite3
import random
import asyncio
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

TOKEN = "8978386324:AAFMndK8IrfTrsAR3pnTXQJMs7sdeh-CeCs"

DB_NAME = "minecraft_community.db"

# Boss
BOSS_INTERVAL = 30 * 60       # 30 minutda yangi boss
BOSS_DURATION = 20 * 60       # boss 20 minut yashaydi
BOSS_MIN_HP = 1000
BOSS_MAX_HP = 2500

# Attack
ATTACK_MIN_DAMAGE = 50
ATTACK_MAX_DAMAGE = 150
ATTACK_COOLDOWN = 3           # 3 sekund

# Events
EVENT_INTERVAL = 20 * 60
EVENT_DURATION = 10 * 60

# Quiz
QUIZ_INTERVAL = 30 * 60


# =========================================================
# DATABASE
# =========================================================

def connect():
    return sqlite3.connect(DB_NAME)


def init_db():

    con = connect()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            chat_id INTEGER,
            name TEXT,

            xp INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            streak INTEGER DEFAULT 0,
            rating INTEGER DEFAULT 0,

            faction TEXT,

            mission_name TEXT,
            mission_progress INTEGER DEFAULT 0,
            mission_target INTEGER DEFAULT 0,
            mission_reward INTEGER DEFAULT 0,

            last_bonus TEXT,

            PRIMARY KEY (user_id, chat_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bosses (
            chat_id INTEGER PRIMARY KEY,
            name TEXT,
            hp INTEGER,
            max_hp INTEGER,
            expires TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boss_damage (
            chat_id INTEGER,
            user_id INTEGER,
            name TEXT,
            damage INTEGER DEFAULT 0,

            PRIMARY KEY (chat_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            chat_id INTEGER PRIMARY KEY,
            name TEXT,
            description TEXT,
            expires TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS hall_of_fame (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            season INTEGER,
            name TEXT,
            rank TEXT,
            xp INTEGER
        )
    """)

    con.commit()
    con.close()


# =========================================================
# CHAT
# =========================================================

def register_chat(chat):

    if not chat:
        return

    con = connect()
    cur = con.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO chats
        (chat_id, title)
        VALUES (?, ?)
    """, (
        chat.id,
        chat.title or "Private"
    ))

    con.commit()
    con.close()


# =========================================================
# USER
# =========================================================

def create_user(user, chat_id):

    con = connect()
    cur = con.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users
        (user_id, chat_id, name)
        VALUES (?, ?, ?)
    """, (
        user.id,
        chat_id,
        user.first_name
    ))

    cur.execute("""
        UPDATE users
        SET name = ?
        WHERE user_id = ? AND chat_id = ?
    """, (
        user.first_name,
        user.id,
        chat_id
    ))

    con.commit()
    con.close()


def get_user(user_id, chat_id):

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE user_id = ? AND chat_id = ?
    """, (
        user_id,
        chat_id
    ))

    result = cur.fetchone()

    con.close()

    return result


# =========================================================
# RANK
# =========================================================

def get_rank(level):

    if level >= 30:
        return "👑 LEGEND"

    if level >= 20:
        return "💎 MASTER"

    if level >= 15:
        return "⚔️ WARRIOR"

    if level >= 10:
        return "🔥 ELITE"

    if level >= 5:
        return "🛡️ KILLER"

    return "🌱 MC"


# =========================================================
# ACTIVITY
# =========================================================

def add_activity(user, chat_id):

    create_user(user, chat_id)

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            xp,
            coins,
            messages,
            level,
            streak,
            rating
        FROM users
        WHERE user_id = ? AND chat_id = ?
    """, (
        user.id,
        chat_id
    ))

    data = cur.fetchone()

    xp, coins, messages, level, streak, rating = data

    messages += 1
    xp += 5
    coins += 1
    rating += 1

    new_level = 1 + (xp // 100)

    if new_level < 1:
        new_level = 1

    cur.execute("""
        UPDATE users
        SET
            xp = ?,
            coins = ?,
            messages = ?,
            level = ?,
            streak = ?,
            rating = ?
        WHERE user_id = ? AND chat_id = ?
    """, (
        xp,
        coins,
        messages,
        new_level,
        streak,
        rating,
        user.id,
        chat_id
    ))

    # Mission: messages
    cur.execute("""
        SELECT mission_name, mission_progress, mission_target
        FROM users
        WHERE user_id = ? AND chat_id = ?
    """, (
        user.id,
        chat_id
    ))

    mission_data = cur.fetchone()

    if mission_data:

        mission_name, progress, target = mission_data

        if mission_name and "xabar" in mission_name.lower():

            if progress < target:

                progress += 1

                cur.execute("""
                    UPDATE users
                    SET mission_progress = ?
                    WHERE user_id = ? AND chat_id = ?
                """, (
                    progress,
                    user.id,
                    chat_id
                ))

    con.commit()
    con.close()

    return (
        xp,
        coins,
        messages,
        new_level,
        streak,
        rating
    )


def update_world_progress(chat_id):
    pass


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    register_chat(update.effective_chat)

    if update.effective_user:

        create_user(
            update.effective_user,
            chat_id
        )

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>MINECRAFT COMMUNITY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🎮 Minecraft Community RPG tizimiga xush kelibsiz!\n\n"

        "📊 /stats — profilingiz\n"
        "🏆 /top — TOP o‘yinchilar\n"
        "🎁 /bonus — kunlik bonus\n"
        "🧠 /quiz — Minecraft quiz\n"
        "🌍 /world — community world\n"
        "💀 /boss — World Boss\n"
        "⚔️ /attack — Bossga hujum\n"
        "🎯 /mission — Secret Mission\n"
        "⚔️ /faction — Faction tanlash\n"
        "📈 /activity — Community statistikasi\n"
        "🏛️ /hall — Hall of Fame\n\n"

        "🔥 <b>Level up. Fight. Dominate.</b>",
        parse_mode="HTML"
    )


# =========================================================
# HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "📖 <b>COMMANDS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "👤 PROFILE\n"
        "/stats\n"
        "/top\n"
        "/bonus\n\n"

        "⚔️ COMMUNITY\n"
        "/faction\n"
        "/mission\n"
        "/activity\n"
        "/hall\n\n"

        "🧠 QUIZ\n"
        "/quiz\n\n"

        "🌍 WORLD\n"
        "/world\n\n"

        "💀 BOSS\n"
        "/boss\n"
        "/attack\n",
        parse_mode="HTML"
    )


# =========================================================
# STATS
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    chat_id = update.effective_chat.id

    create_user(user, chat_id)

    data = get_user(
        user.id,
        chat_id
    )

    (
        user_id,
        db_chat_id,
        name,
        xp,
        coins,
        messages,
        level,
        streak,
        rating,
        faction,
        mission_name,
        mission_progress,
        mission_target,
        mission_reward,
        last_bonus
    ) = data

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>PLAYER PROFILE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 {name}\n"
        f"🆙 Level: <b>{level}</b>\n"
        f"🏅 Rank: <b>{get_rank(level)}</b>\n\n"

        f"⭐ XP: <b>{xp}</b>\n"
        f"💰 Coins: <b>{coins}</b>\n"
        f"📊 Rating: <b>{rating}</b>\n"
        f"💬 Messages: <b>{messages}</b>\n"
        f"🔥 Streak: <b>{streak}</b>\n\n"

        f"⚔️ Faction: <b>{faction or 'Tanlanmagan'}</b>",
        parse_mode="HTML"
    )


# =========================================================
# TOP
# =========================================================

async def top(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT name, level, xp, rating
        FROM users
        WHERE chat_id = ?
        ORDER BY xp DESC
        LIMIT 10
    """, (
        chat_id,
    ))

    rows = cur.fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "🏆 Hali TOP bo‘sh."
        )

        return

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🏆 <b>COMMUNITY TOP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, row in enumerate(rows, 1):

        name, level, xp, rating = row

        medal = medals[i - 1] if i <= 3 else f"{i}."

        text += (
            f"{medal} <b>{name}</b>\n"
            f"   🆙 Level {level} | ⭐ {xp} XP | 📊 {rating}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# BONUS
# =========================================================

async def bonus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    chat_id = update.effective_chat.id

    create_user(user, chat_id)

    today = datetime.now().strftime("%Y-%m-%d")

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT last_bonus
        FROM users
        WHERE user_id = ? AND chat_id = ?
    """, (
        user.id,
        chat_id
    ))

    last = cur.fetchone()[0]

    if last == today:

        con.close()

        await update.message.reply_text(
            "🎁 Bugungi bonusni allaqachon olgansiz."
        )

        return

    xp_reward = random.randint(50, 100)
    coin_reward = random.randint(20, 50)

    cur.execute("""
        UPDATE users
        SET
            xp = xp + ?,
            coins = coins + ?,
            rating = rating + 5,
            last_bonus = ?
        WHERE user_id = ? AND chat_id = ?
    """, (
        xp_reward,
        coin_reward,
        today,
        user.id,
        chat_id
    ))

    con.commit()
    con.close()

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>DAILY BONUS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"⭐ +{xp_reward} XP\n"
        f"💰 +{coin_reward} Coins\n"
        "📊 +5 Rating\n\n"

        "⏰ Ertaga yana qayting!",
        parse_mode="HTML"
    )


# =========================================================
# QUIZ
# =========================================================

QUIZ_QUESTIONS = [
    ("Minecraft Java'da Nether portalining minimal o'lchami qanday?",
     ["2x3", "3x3", "4x5", "5x5"], 2),

    ("Java Edition'da maksimal enchantment levelini oshirish uchun qaysi buyruq ishlatiladi?",
     ["/enchant", "/give", "/effect", "/attribute"], 0),

    ("Warden qaysi mobni ko'rish orqali emas, asosan qaysi mexanizm orqali sezadi?",
     ["Light", "Vibration", "Water", "Fire"], 1),

    ("Sculk Sensor qaysi hodisani aniqlay oladi?",
     ["Vibrations", "Faqat yorug'lik", "Faqat moblar", "Faqat redstone"], 0),

    ("Sculk Catalyst mob o'lganda nima hosil qiladi?",
     ["Sculk", "Obsidian", "Soul Sand", "Amethyst"], 0),

    ("Warden qaysi effektni o'yinchiga beradi?",
     ["Darkness", "Blindness", "Mining Fatigue", "Weakness"], 0),

    ("Beacon maksimal kuchda nechta qatlamli piramidaga ega bo'ladi?",
     ["3", "4", "5", "6"], 1),

    ("Beacon piramidasining eng pastki qatlami maksimal nechta blokdan iborat?",
     ["9", "25", "49", "81"], 3),

    ("Beacon beam qaysi blokdan o'ta olmaydi?",
     ["Glass", "Water", "Bedrock", "Leaves"], 2),

    ("Nether Star qaysi mobdan tushadi?",
     ["Wither", "Warden", "Ghast", "Ender Dragon"], 0),

    ("Wither qaysi HP chegarasida yangi hujum bosqichiga o'tadi?",
     ["75%", "50%", "25%", "10%"], 1),

    ("Wither ikkinchi bosqichda qanday hujumga ega bo'ladi?",
     ["Uchadi", "Armor oladi", "Teleport qiladi", "Invisible bo'ladi"], 1),

    ("Ender Dragonni qayta chaqirish uchun nechta End Crystal kerak?",
     ["2", "4", "6", "8"], 1),

    ("End Crystal qaysi blok ustiga qo'yilishi mumkin?",
     ["Obsidian yoki Bedrock", "Stone", "Iron Block", "End Stone"], 0),

    ("Dragon Egg odatda Ender Dragon mag'lub bo'lgandan keyin qayerda paydo bo'ladi?",
     ["End City", "Exit Portal", "Stronghold", "Spawn Point"], 1),

    ("End Gateway qanday usul bilan ochilishi mumkin?",
     ["Ender Dragonni qayta chaqirish va mag'lub qilish",
      "Wither chaqirish", "100 ta Enderman o'ldirish", "Beacon qurish"], 0),

    ("End City ko'pincha qaysi biome'da joylashadi?",
     ["The End", "End Highlands", "End Midlands", "Void"], 1),

    ("Elytra qayerdan topiladi?",
     ["Stronghold", "End City Ship", "Nether Fortress", "Ancient City"], 1),

    ("Elytra bilan uchishda qaysi item tezlikni oshiradi?",
     ["Firework Rocket", "Arrow", "Snowball", "Ender Pearl"], 0),

    ("Shulker Box'ning eng muhim xususiyati nima?",
     ["Ichidagi itemlar blok sindirilganda saqlanadi",
      "Cheksiz item beradi", "O'z-o'zidan ochiladi", "Redstone generator"], 0),

    ("Shulker qaysi effektni beradi?",
     ["Levitation", "Slow Falling", "Glowing", "Weakness"], 0),

    ("Shulker projectile blokka urilganda nima bo'lishi mumkin?",
     ["Levitation beradi", "Burns", "Explode qiladi", "Teleport qiladi"], 0),

    ("Ancient City qaysi biome'da hosil bo'ladi?",
     ["Deep Dark", "Lush Cave", "Dripstone Cave", "Deep Ocean"], 0),

    ("Ancient City'dagi eng xavfli mob qaysi?",
     ["Warden", "Ravager", "Evoker", "Wither"], 0),

    ("Trial Chamber qaysi yangi jangovar tizim bilan bog'liq?",
     ["Trial Spawner", "Raid Captain", "Dragon Egg", "Beacon"], 0),

    ("Breeze asosan qaysi joyda uchraydi?",
     ["Trial Chamber", "Ancient City", "Nether Fortress", "Stronghold"], 0),

    ("Breeze'ning asosiy projectile'i nima deb ataladi?",
     ["Wind Charge", "Wind Ball", "Air Shot", "Gust Orb"], 0),

    ("Wind Charge nima qila oladi?",
     ["O'yinchini yoki entityni knockback qiladi",
      "Suvni muzlatadi", "Nether portal ochadi", "Moblarni heal qiladi"], 0),

    ("Mace uchun Density enchantmenti nimani kuchaytiradi?",
     ["Falling attack damage", "Mining speed", "Movement speed", "Durability"], 0),

    ("Mace uchun Breach enchantmenti nimaga qarshi foydali?",
     ["Armor", "Fire", "Potions", "Shields"], 0),

    ("Mace uchun Wind Burst nimaga imkon beradi?",
     ["Smash hujumidan keyin o'yinchini yuqoriga qaytaradi",
      "Suvda tez yuradi", "Teleport qiladi", "Invisible qiladi"], 0),

    ("Minecraft Java'da Critical Hit qachon bajariladi?",
     ["O'yinchi havoda tushayotgan paytda hujum qilsa",
      "Sprint qilganda", "Sneak qilganda", "Suvda turganda"], 0),

    ("Critical Hit qaysi holatda bajarilmaydi?",
     ["O'yinchi to'liq yerda turganda",
      "O'yinchi yiqilayotganda", "Jumpdan tushayotganda", "Fall bilan hujum qilganda"], 0),

    ("Sweeping Edge enchantmenti nimani kuchaytiradi?",
     ["Sweep attack", "Critical damage", "Bow damage", "Fire damage"], 0),

    ("Looting enchantmentining asosiy vazifasi nima?",
     ["Mob drop miqdorini oshirish",
      "XPni ikki baravar qilish", "Weapon durabilityni oshirish", "Armorni kuchaytirish"], 0),

    ("Fortune enchantmenti qaysi turdagi bloklardan ko'proq drop olishga yordam beradi?",
     ["Certain ores/crops", "Obsidian", "Bedrock", "End Portal"], 0),

    ("Silk Touch bilan qaysi blokni olish mumkin?",
     ["Glass", "Bedrock", "End Portal Frame", "Spawner"], 0),

    ("Silk Touch bilan Spawnerni odatiy survival'da olish mumkinmi?",
     ["Yo'q", "Ha", "Faqat Netherda", "Faqat Endda"], 0),

    ("Mending enchantmenti itemni qanday tiklaydi?",
     ["XP orqali", "Coal orqali", "Iron orqali", "Food orqali"], 0),

    ("Unbreaking enchantmenti nima qiladi?",
     ["Item durability kamayish ehtimolini pasaytiradi",
      "Damage ikki baravar bo'ladi", "XP oshadi", "Speed oshadi"], 0),

    ("Infinity enchantmenti qaysi item uchun mashhur?",
     ["Bow", "Sword", "Shield", "Pickaxe"], 0),

    ("Infinity va Mending bir bow'da Java Edition'da odatiy enchantment sifatida birga qo'yiladimi?",
     ["Yo'q", "Ha", "Faqat Netherda", "Faqat Creative'da"], 0),

    ("Riptide enchantmenti qachon ishlaydi?",
     ["Suvda yoki yomg'irda", "Faqat Netherda", "Faqat quruqlikda", "Faqat Endda"], 0),

    ("Channeling enchantmenti nima qilishi mumkin?",
     ["Momaqaldiroq paytida lightning chaqirishi mumkin",
      "Suv yaratadi", "Mobni freeze qiladi", "Teleport qiladi"], 0),

    ("Loyalty enchantmenti qaysi qurolga tegishli?",
     ["Trident", "Mace", "Bow", "Crossbow"], 0),

    ("Soul Speed qaysi bloklarda tezlik beradi?",
     ["Soul Sand va Soul Soil", "Ice", "Stone", "End Stone"], 0),

    ("Frost Walker enchantmenti nima qiladi?",
     ["Suv ustida muz hosil qiladi", "Lava ustida yuradi",
      "Yomg'irni to'xtatadi", "Snowball beradi"], 0),

    ("Depth Strider nimani tezlashtiradi?",
     ["Suvdagi harakatni", "Yugurishni", "Flyingni", "Miningni"], 0),

    ("Aqua Affinity nimani tezlashtiradi?",
     ["Suv ostidagi mining", "Suvda yurish", "Fishing", "Swimming damage"], 0),

    ("Respiration enchantmenti nima beradi?",
     ["Suv ostida uzoqroq nafas olish",
      "Ko'proq damage", "Tezroq yugurish", "Night Vision"], 0),

    ("Totem of Undying qaysi mobdan tushadi?",
     ["Evoker", "Vindicator", "Pillager", "Ravager"], 0),

    ("Evoker qaysi hujumdan foydalanadi?",
     ["Fangs", "Fireball", "Wind Charge", "Dragon Breath"], 0),

    ("Totem ishlaganda o'yinchiga qaysi effektlardan biri beriladi?",
     ["Regeneration", "Haste", "Mining Fatigue", "Glowing only"], 0),

    ("Raid'ni boshlash uchun odatda qaysi effekt kerak?",
     ["Bad Omen", "Hero of the Village", "Darkness", "Ominous"], 0),

    ("Raid tugagandan keyin qaysi effekt beriladi?",
     ["Hero of the Village", "Bad Omen", "Glowing", "Strength"], 0),

    ("Hero of the Village nima beradi?",
     ["Village savdolarida chegirmalar va bonuslar",
      "Permanent Strength", "Night Vision", "Flying"], 0),

    ("Ravager qaysi event bilan bog'liq?",
     ["Raid", "Trial", "End", "Nether"], 0),

    ("Pillager Outpost'da qaysi mob ko'p uchraydi?",
     ["Pillager", "Evoker", "Warden", "Piglin Brute"], 0),

    ("Piglin Brute qayerda uchraydi?",
     ["Bastion Remnant", "Nether Fortress", "Stronghold", "End City"], 0),

    ("Piglin qaysi itemni kiygan o'yinchiga odatda hujum qilmaydi?",
     ["Gold armor", "Diamond armor", "Iron armor", "Netherite armor"], 0),

    ("Piglin bilan barter qilish uchun nima kerak?",
     ["Gold Ingot", "Gold Nugget", "Emerald", "Diamond"], 0),

    ("Piglin barterida qaysi item juda foydali?",
     ["Ender Pearl", "Diamond", "Elytra", "Nether Star"], 0),

    ("Netherite upgrade template qayerdan topiladi?",
     ["Bastion Remnant", "Nether Fortress", "Stronghold", "Village"], 0),

    ("Netherite upgrade qilishda diamond gear ustiga nima qo'shiladi?",
     ["Netherite Ingot", "Netherite Scrap", "Ancient Debris", "Gold Block"], 0),

    ("Ancient Debris qaysi o'lchamda topiladi?",
     ["Nether", "Overworld", "End", "Deep Dark"], 0),

    ("Ancient Debris qaysi blok bilan portlashga chidamli?",
     ["Obsidian darajasiga yaqin", "Glass", "Dirt", "Wood"], 0),

    ("Netherite itemlar lava ichida nima qiladi?",
     ["Suzib turadi", "Darhol yo'qoladi", "Yonadi", "Obsidian bo'ladi"], 0),

    ("Nether Fortress'da qaysi mobning spawneri uchraydi?",
     ["Blaze", "Warden", "Shulker", "Breeze"], 0),

    ("Blaze Rod qaysi mobdan tushadi?",
     ["Blaze", "Ghast", "Magma Cube", "Wither Skeleton"], 0),

    ("Blaze Powder nimani tayyorlashda kerak?",
     ["Eye of Ender", "End Crystal", "Beacon", "Elytra"], 0),

    ("Eye of Ender qaysi ikki asosiy itemdan tayyorlanadi?",
     ["Ender Pearl + Blaze Powder",
      "Ender Pearl + Ghast Tear",
      "Blaze Rod + Diamond",
      "Obsidian + Blaze Powder"], 0),

    ("Strongholdni topishda qaysi item yordam beradi?",
     ["Eye of Ender", "Compass", "Recovery Compass", "Spyglass"], 0),

    ("End Portal Frame'ni Survival'da oddiy usulda olish mumkinmi?",
     ["Yo'q", "Ha", "Faqat Fortune bilan", "Faqat Silk Touch bilan"], 0),

    ("End Portal odatda qayerda joylashadi?",
     ["Stronghold", "End City", "Ancient City", "Bastion"], 0),

    ("Compass qaysi joyda odatda foydasiz yo'nalish ko'rsatishi mumkin?",
     ["Nether", "Overworld", "Village", "Ocean"], 0),

    ("Lodestone Compass nimaga bog'lanadi?",
     ["Lodestone", "Beacon", "Respawn Anchor", "End Portal"], 0),

    ("Recovery Compass nimani ko'rsatadi?",
     ["Oxirgi o'lim joyini", "Spawn pointni", "Strongholdni", "Village'ni"], 0),

    ("Recovery Compass qaysi materialni talab qiladi?",
     ["Echo Shard", "Amethyst Shard", "Prismarine", "Quartz"], 0),

    ("Echo Shard qayerdan topiladi?",
     ["Ancient City", "End City", "Stronghold", "Bastion"], 0),

    ("Conduit qanday bloklar bilan quriladi?",
     ["Prismarine/Sea Lantern bloklari",
      "Obsidian", "Iron Block", "Copper Block"], 0),

    ("Conduit suv ostida qanday bonus beradi?",
     ["Conduit Power", "Haste", "Strength", "Fire Resistance"], 0),

    ("Tridentni oddiy crafting table'da craft qilish mumkinmi?",
     ["Yo'q", "Ha", "Faqat Netherda", "Faqat Endda"], 0),

    ("Trident asosan qaysi mobdan olinadi?",
     ["Drowned", "Guardian", "Elder Guardian", "Zombie"], 0),

    ("Elder Guardian o'yinchiga qaysi effektni beradi?",
     ["Mining Fatigue", "Darkness", "Weakness", "Slowness"], 0),

    ("Ocean Monumentning asosiy guardian moblaridan biri qaysi?",
     ["Elder Guardian", "Warden", "Evoker", "Shulker"], 0),

    ("Guardian qaysi attackdan foydalanadi?",
     ["Laser", "Arrow", "Fireball", "Wind Charge"], 0),

    ("Dolphin's Grace effekti Java Edition'da qanday olinadi?",
     ["Dolphin yaqinida suzish orqali",
      "Dolphinni o'ldirish orqali", "Fish berish orqali", "Potion orqali"], 0),

    ("Turtle Shell qaysi helmet effektini beradi?",
     ["Water Breathing", "Night Vision", "Conduit Power", "Dolphin's Grace"], 0),

    ("Turtle Scute qayerdan olinadi?",
     ["Baby turtle ulg'ayganda", "Turtle o'lganda", "Fishingdan", "Ocean Monumentdan"], 0),

    ("Villager zombiga aylantirilib yana davolansa nima bo'lishi mumkin?",
     ["Savdo narxlari pasayadi", "XP yo'qoladi", "Village yo'qoladi", "Villager teleport qiladi"], 0),

    ("Zombie Villager'ni davolash uchun nima kerak?",
     ["Weakness + Golden Apple", "Strength + Apple",
      "Regeneration + Gold", "Potion of Healing + Emerald"], 0),

    ("Villager qaysi blok orqali Librarian kasbini oladi?",
     ["Lectern", "Bookshelf", "Cartography Table", "Stonecutter"], 0),

    ("Villager qaysi blok orqali Armorer bo'ladi?",
     ["Blast Furnace", "Smithing Table", "Anvil", "Furnace"], 0),

    ("Villager qaysi blok orqali Toolsmith bo'ladi?",
     ["Smithing Table", "Grindstone", "Stonecutter", "Anvil"], 0),

    ("Villager qaysi blok orqali Weaponsmith bo'ladi?",
     ["Grindstone", "Smithing Table", "Anvil", "Blast Furnace"], 0),

    ("Java Edition'da villager trade'larini yangilashning asosiy usuli nima?",
     ["Workstation bilan ishlash", "Uni urish", "Uni boqish", "Uni uxlatmaslik"], 0),

    ("Redstone signalining oddiy maksimal kuchi nechaga teng?",
     ["15", "10", "20", "255"], 0),

    ("Redstone repeater signalni necha blokdan keyin qayta kuchaytiradi?",
     ["15 blok", "10 blok", "20 blok", "5 blok"], 0),

    ("Comparator qaysi maxsus vazifani bajarishi mumkin?",
     ["Container signalini o'qish", "Faqat piston boshqarish",
      "Faqat lampani yoqish", "Faqat eshik ochish"], 0),

    ("Hopper itemlarni qaysi yo'nalishda uzatishi mumkin?",
     ["Yuqoridan pastga va yon tomondan", "Faqat yuqoriga",
      "Faqat pastga", "Faqat diagonal"], 0),

    ("Observer nimani aniqlaydi?",
     ["Block state change", "Faqat moblarni", "Faqat itemlarni", "Faqat yorug'likni"], 0),

    ("Piston qaysi blokni odatda siljita olmaydi?",
     ["Obsidian", "Stone", "Dirt", "Glass"], 0),

    ("Sticky Pistonning oddiy pistondan asosiy farqi nima?",
     ["Blokni qaytarib torta oladi", "Tezroq ishlaydi",
      "Ko'proq blok itaradi", "Redstone talab qilmaydi"], 0),

    ("Minecraft Java'da hopper orqali nechta item bir vaqtning o'zida o'tadi?",
     ["1", "5", "16", "64"], 0),
]


async def quiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    question, answers, correct = random.choice(
        QUIZ_QUESTIONS
    )

    keyboard = []

    for i, answer in enumerate(answers):

        keyboard.append([
            InlineKeyboardButton(
                answer,
                callback_data=f"quiz:{correct}:{i}"
            )
        ])

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 <b>MINECRAFT QUIZ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"❓ {question}",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
        parse_mode="HTML"
    )


async def quiz_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    parts = query.data.split(":")

    correct = int(parts[1])
    selected = int(parts[2])

    user = query.from_user
    chat_id = query.message.chat.id

    create_user(
        user,
        chat_id
    )

    if selected == correct:

        xp = random.randint(30, 60)
        coins = random.randint(10, 25)

        con = connect()
        cur = con.cursor()

        cur.execute("""
            UPDATE users
            SET
                xp = xp + ?,
                coins = coins + ?,
                rating = rating + 5
            WHERE user_id = ? AND chat_id = ?
        """, (
            xp,
            coins,
            user.id,
            chat_id
        ))

        con.commit()
        con.close()

        await query.edit_message_text(
            "✅ <b>TO‘G‘RI JAVOB!</b>\n\n"
            f"👤 {user.first_name}\n"
            f"⭐ +{xp} XP\n"
            f"💰 +{coins} Coins\n"
            "📊 +5 Rating",
            parse_mode="HTML"
        )

    else:

        await query.edit_message_text(
            "❌ <b>NOTO‘G‘RI!</b>\n\n"
            "Keyingi quizda omad!",
            parse_mode="HTML"
        )


# =========================================================
# WORLD
# =========================================================

async def world(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(messages), 0),
            COALESCE(SUM(xp), 0)
        FROM users
        WHERE chat_id = ?
    """, (
        chat_id,
    ))

    players, messages, xp = cur.fetchone()

    con.close()

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "🌍 <b>COMMUNITY WORLD</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Players: <b>{players}</b>\n"
        f"💬 Messages: <b>{messages}</b>\n"
        f"⭐ Total XP: <b>{xp}</b>\n\n"

        "🌎 World rivojlanmoqda...\n"
        "⚔️ Community birgalikda kuchaymoqda!",
        parse_mode="HTML"
    )


# =========================================================
# BOSS
# =========================================================

BOSS_NAMES = [
    "WITHER",
    "WARDEN",
    "ENDER DRAGON"
]


async def boss(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    register_chat(
        update.effective_chat
    )

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            name,
            hp,
            max_hp,
            expires
        FROM bosses
        WHERE chat_id = ?
    """, (
        chat_id,
    ))

    result = cur.fetchone()

    con.close()

    if not result:

        await update.message.reply_text(
            "💀 Hozir aktiv World Boss yo‘q."
        )

        return

    name, hp, max_hp, expires = result

    if datetime.now() >= datetime.fromisoformat(
        expires
    ):

        await update.message.reply_text(
            "💀 Boss event tugagan."
        )

        return

    percent = max(
        0,
        int((hp / max_hp) * 100)
    )

    # HP bar
    filled = int(percent / 10)

    bar = (
        "█" * filled +
        "░" * (10 - filled)
    )

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "💀 <b>WORLD BOSS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"☠️ <b>{name}</b>\n"
        f"❤️ HP: <b>{hp:,}</b> / {max_hp:,}\n"
        f"📊 {bar} {percent}%\n\n"

        "⚔️ /attack — bossga hujum\n"
        "🏆 Eng ko‘p damage qilganlar TOP 3 oladi!",
        parse_mode="HTML"
    )


# =========================================================
# ATTACK COOLDOWN
# =========================================================

attack_times = {}


# =========================================================
# ATTACK BOSS
# =========================================================

async def attack(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    chat_id = update.effective_chat.id

    create_user(
        user,
        chat_id
    )

    # Cooldown
    key = (
        chat_id,
        user.id
    )

    now = datetime.now()

    if key in attack_times:

        diff = (
            now - attack_times[key]
        ).total_seconds()

        if diff < ATTACK_COOLDOWN:

            left = round(
                ATTACK_COOLDOWN - diff,
                1
            )

            await update.message.reply_text(
                f"⏳ Hali {left} sekund kuting."
            )

            return

    attack_times[key] = now

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            name,
            hp,
            max_hp,
            expires
        FROM bosses
        WHERE chat_id = ?
    """, (
        chat_id,
    ))

    result = cur.fetchone()

    if not result:

        con.close()

        await update.message.reply_text(
            "💀 Hozir boss mavjud emas."
        )

        return

    name, hp, max_hp, expires = result

    if datetime.now() >= datetime.fromisoformat(
        expires
    ):

        con.close()

        await update.message.reply_text(
            "💀 Boss event tugagan."
        )

        return

    # DAMAGE
    damage = random.randint(
        ATTACK_MIN_DAMAGE,
        ATTACK_MAX_DAMAGE
    )

    new_hp = max(
        0,
        hp - damage
    )

    # Player reward
    xp_reward = random.randint(
        10,
        25
    )

    coin_reward = random.randint(
        3,
        10
    )

    # Boss HP
    cur.execute("""
        UPDATE bosses
        SET hp = ?
        WHERE chat_id = ?
    """, (
        new_hp,
        chat_id
    ))

    # User reward
    cur.execute("""
        UPDATE users
        SET
            xp = xp + ?,
            coins = coins + ?,
            rating = rating + 3
        WHERE user_id = ? AND chat_id = ?
    """, (
        xp_reward,
        coin_reward,
        user.id,
        chat_id
    ))

    # Boss damage leaderboard
    cur.execute("""
        INSERT INTO boss_damage
        (chat_id, user_id, name, damage)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            damage = damage + excluded.damage,
            name = excluded.name
    """, (
        chat_id,
        user.id,
        user.first_name,
        damage
    ))

    defeated = new_hp <= 0

    if defeated:

        # TOP damage
        cur.execute("""
            SELECT
                user_id,
                name,
                damage
            FROM boss_damage
            WHERE chat_id = ?
            ORDER BY damage DESC
            LIMIT 3
        """, (
            chat_id,
        ))

        top_damage = cur.fetchall()

        # Reward TOP 3
        rewards = [
            (300, 150, 100),
            (200, 100, 70),
            (100, 50, 40)
        ]

        for index, row in enumerate(
            top_damage
        ):

            if index >= 3:
                break

            user_id, player_name, total_damage = row

            xp_r, coin_r, rating_r = rewards[index]

            cur.execute("""
                UPDATE users
                SET
                    xp = xp + ?,
                    coins = coins + ?,
                    rating = rating + ?
                WHERE user_id = ? AND chat_id = ?
            """, (
                xp_r,
                coin_r,
                rating_r,
                user_id,
                chat_id
            ))

        # Boshqa qatnashchilar
        cur.execute("""
            UPDATE users
            SET
                xp = xp + 50,
                coins = coins + 20,
                rating = rating + 20
            WHERE chat_id = ?
            AND user_id IN (
                SELECT user_id
                FROM boss_damage
                WHERE chat_id = ?
            )
        """, (
            chat_id,
            chat_id
        ))

        # Bossni o‘chirish
        cur.execute("""
            DELETE FROM bosses
            WHERE chat_id = ?
        """, (
            chat_id,
        ))

        con.commit()
        con.close()

        text = (
            "━━━━━━━━━━━━━━━━━━\n"
            "☠️ <b>BOSS DEFEATED</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"💀 <b>{name}</b> mag‘lub bo‘ldi!\n\n"
            f"⚔️ Oxirgi zarba: <b>{user.first_name}</b>\n"
            f"💥 Damage: <b>{damage}</b>\n\n"

            "🏆 <b>BOSS DAMAGE TOP</b>\n\n"
        )

        medals = [
            "🥇",
            "🥈",
            "🥉"
        ]

        for index, row in enumerate(
            top_damage
        ):

            player_name = row[1]
            total_damage = row[2]

            text += (
                f"{medals[index]} "
                f"<b>{player_name}</b> — "
                f"{total_damage:,} damage\n"
            )

        text += (
            "\n"
            "🥇 TOP 1: +300 XP / +150 Coins / +100 Rating\n"
            "🥈 TOP 2: +200 XP / +100 Coins / +70 Rating\n"
            "🥉 TOP 3: +100 XP / +50 Coins / +40 Rating\n\n"

            "🔥 Keyingi bossni kuting!"
        )

        await update.message.reply_text(
            text,
            parse_mode="HTML"
        )

        return

    con.commit()
    con.close()

    percent = int(
        (new_hp / max_hp) * 100
    )

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "⚔️ <b>ATTACK!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 <b>{user.first_name}</b>\n"
        f"💥 Damage: <b>{damage}</b>\n"
        f"⭐ +{xp_reward} XP\n"
        f"💰 +{coin_reward} Coins\n"
        "📊 +3 Rating\n\n"

        f"💀 {name} HP: <b>{new_hp:,}</b> / {max_hp:,}\n"
        f"📊 Remaining: <b>{percent}%</b>\n\n"

        "🏆 Ko‘proq damage = yuqoriroq TOP!",
        parse_mode="HTML"
    )


# =========================================================
# BOSS LOOP
# =========================================================

async def boss_loop(app):

    await asyncio.sleep(30)

    while True:

        con = connect()
        cur = con.cursor()

        cur.execute("""
            SELECT chat_id
            FROM chats
        """)

        chats = cur.fetchall()

        con.close()

        for (chat_id,) in chats:

            try:

                con = connect()
                cur = con.cursor()

                cur.execute("""
                    SELECT
                        name,
                        expires
                    FROM bosses
                    WHERE chat_id = ?
                """, (
                    chat_id,
                ))

                exists = cur.fetchone()

                # Eski boss tugagan bo‘lsa o‘chirish
                if exists:

                    name, expires = exists

                    if datetime.now() >= datetime.fromisoformat(
                        expires
                    ):

                        cur.execute("""
                            DELETE FROM bosses
                            WHERE chat_id = ?
                        """, (
                            chat_id,
                        ))

                        cur.execute("""
                            DELETE FROM boss_damage
                            WHERE chat_id = ?
                        """, (
                            chat_id,
                        ))

                        con.commit()

                        exists = None

                con.close()

                if exists:
                    continue

                # Yangi boss
                name = random.choice(
                    BOSS_NAMES
                )

                max_hp = random.randint(
                    BOSS_MIN_HP,
                    BOSS_MAX_HP
                )

                expires = (
                    datetime.now()
                    +
                    timedelta(
                        seconds=BOSS_DURATION
                    )
                ).isoformat()

                con = connect()
                cur = con.cursor()

                cur.execute("""
                    INSERT OR REPLACE INTO bosses
                    (chat_id, name, hp, max_hp, expires)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    chat_id,
                    name,
                    max_hp,
                    max_hp,
                    expires
                ))

                # Damage jadvalini tozalash
                cur.execute("""
                    DELETE FROM boss_damage
                    WHERE chat_id = ?
                """, (
                    chat_id,
                ))

                con.commit()
                con.close()

                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "━━━━━━━━━━━━━━━━━━\n"
                        "💀 <b>WORLD BOSS SPAWNED</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n\n"

                        f"☠️ <b>{name}</b>\n"
                        f"❤️ HP: <b>{max_hp:,}</b>\n\n"

                        "⚔️ Community birgalikda "
                        "bossni yengishi kerak!\n\n"

                        "/boss\n"
                        "/attack\n\n"

                        "🏆 Eng ko‘p damage qilgan "
                        "TOP 3 bonus oladi!"
                    ),
                    parse_mode="HTML"
                )

            except Exception as e:

                print(
                    "Boss error:",
                    e
                )

        await asyncio.sleep(
            BOSS_INTERVAL
        )


# =========================================================
# MISSIONS
# =========================================================

MISSIONS = [

    (
        "100 ta xabar yoz",
        100,
        150
    ),

    (
        "50 ta xabar yoz",
        50,
        100
    ),

    (
        "10 ta quizda qatnash",
        10,
        200
    ),

    (
        "500 XP yig‘",
        500,
        250
    )

]


def assign_mission(
    user_id,
    chat_id
):

    mission_data = random.choice(
        MISSIONS
    )

    name, target, reward = mission_data

    con = connect()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET
            mission_name = ?,
            mission_progress = 0,
            mission_target = ?,
            mission_reward = ?
        WHERE user_id = ? AND chat_id = ?
    """, (
        name,
        target,
        reward,
        user_id,
        chat_id
    ))

    con.commit()
    con.close()


async def mission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    chat_id = update.effective_chat.id

    create_user(
        user,
        chat_id
    )

    data = get_user(
        user.id,
        chat_id
    )

    mission_name = data[10]
    progress = data[11]
    target = data[12]
    reward = data[13]

    if not mission_name:

        assign_mission(
            user.id,
            chat_id
        )

        data = get_user(
            user.id,
            chat_id
        )

        mission_name = data[10]
        progress = data[11]
        target = data[12]
        reward = data[13]

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "🔒 <b>SECRET MISSION</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"🎯 {mission_name}\n\n"
        f"📊 Progress: <b>{progress}/{target}</b>\n"
        f"⭐ Reward: <b>{reward} XP</b>",
        parse_mode="HTML"
    )


# =========================================================
# FACTION
# =========================================================

async def faction(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🔥 NETHER",
                callback_data="faction:NETHER"
            )
        ],

        [
            InlineKeyboardButton(
                "🟣 END",
                callback_data="faction:END"
            )
        ],

        [
            InlineKeyboardButton(
                "🌍 OVERWORLD",
                callback_data="faction:OVERWORLD"
            )
        ]

    ])

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "⚔️ <b>CHOOSE YOUR FACTION</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🔥 NETHER — agressive players\n"
        "🟣 END — elite players\n"
        "🌍 OVERWORLD — balanced players\n\n"

        "Tanlaganingiz profilingizda saqlanadi.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


async def faction_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    faction_name = query.data.split(":")[1]

    user = query.from_user
    chat_id = query.message.chat.id

    create_user(
        user,
        chat_id
    )

    con = connect()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET faction = ?
        WHERE user_id = ? AND chat_id = ?
    """, (
        faction_name,
        user.id,
        chat_id
    ))

    con.commit()
    con.close()

    await query.edit_message_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "⚔️ <b>FACTION SELECTED</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 {user.first_name}\n"
        f"⚔️ Faction: <b>{faction_name}</b>\n\n"

        "🔥 Welcome to the faction.",
        parse_mode="HTML"
    )


# =========================================================
# ACTIVITY
# =========================================================

async def activity_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    register_chat(
        update.effective_chat
    )

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(messages), 0),
            COALESCE(SUM(xp), 0)
        FROM users
        WHERE chat_id = ?
    """, (
        chat_id,
    ))

    users, messages, xp = cur.fetchone()

    con.close()

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>COMMUNITY ACTIVITY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 Players: <b>{users}</b>\n"
        f"💬 Messages: <b>{messages}</b>\n"
        f"⭐ Total XP: <b>{xp}</b>",
        parse_mode="HTML"
    )


# =========================================================
# HALL OF FAME
# =========================================================

async def hall(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    con = connect()
    cur = con.cursor()

    cur.execute("""
        SELECT
            season,
            name,
            rank,
            xp
        FROM hall_of_fame
        WHERE chat_id = ?
        ORDER BY season DESC, xp DESC
        LIMIT 10
    """, (
        chat_id,
    ))

    rows = cur.fetchall()

    con.close()

    if not rows:

        await update.message.reply_text(
            "🏛️ Hall of Fame hali bo‘sh."
        )

        return

    text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🏛️ <b>HALL OF FAME</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    for season, name, rank, xp in rows:

        text += (
            f"🏆 Season {season}\n"
            f"👤 {name}\n"
            f"🏅 {rank}\n"
            f"⭐ {xp} XP\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# RANDOM EVENTS
# =========================================================

EVENTS = [

    (
        "NETHER INVASION",
        "Keyingi event davomida quiz XP mukofotlari oshadi."
    ),

    (
        "END PHASE",
        "Community eng aktiv o‘yinchilarni aniqlaydi."
    ),

    (
        "DOUBLE XP",
        "Community uchun maxsus XP event boshlandi."
    ),

    (
        "DARK HOUR",
        "Eng aktiv o‘yinchilar TOP uchun kurashadi."
    )

]


async def random_event_loop(app):

    await asyncio.sleep(120)

    while True:

        con = connect()
        cur = con.cursor()

        cur.execute("""
            SELECT chat_id
            FROM chats
        """)

        chats = cur.fetchall()

        con.close()

        for (chat_id,) in chats:

            try:

                name, description = random.choice(
                    EVENTS
                )

                expires = (
                    datetime.now()
                    +
                    timedelta(
                        seconds=EVENT_DURATION
                    )
                ).isoformat()

                con = connect()
                cur = con.cursor()

                cur.execute("""
                    INSERT OR REPLACE INTO events
                    (chat_id, name, description, expires)
                    VALUES (?, ?, ?, ?)
                """, (
                    chat_id,
                    name,
                    description,
                    expires
                ))

                con.commit()
                con.close()

                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "━━━━━━━━━━━━━━━━━━\n"
                        "🌑 <b>WORLD EVENT</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n\n"

                        f"⚡ <b>{name}</b>\n\n"
                        f"{description}\n\n"

                        f"⏱️ {EVENT_DURATION // 60} minutes"
                    ),
                    parse_mode="HTML"
                )

            except Exception as e:

                print(
                    "Event error:",
                    e
                )

        await asyncio.sleep(
            EVENT_INTERVAL
        )


# =========================================================
# WELCOME
# =========================================================

async def welcome(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat_id = update.effective_chat.id

    register_chat(
        update.effective_chat
    )

    for member in update.message.new_chat_members:

        if member.is_bot:
            continue

        create_user(
            member,
            chat_id
        )

        await update.message.reply_text(
            f"⚡ <b>{member.first_name}</b> joined!\n\n"

            "Welcome to the Minecraft Community.\n\n"

            "⚔️ /faction\n"
            "🧠 /quiz\n"
            "📊 /stats\n"
            "🎯 /mission\n"
            "💀 /boss\n"
            "⚔️ /attack\n"
            "🏆 /top\n\n"

            "🔥 Climb the ranks.",
            parse_mode="HTML"
        )


# =========================================================
# GROUP ACTIVITY
# =========================================================

async def activity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user

    if not user or user.is_bot:
        return

    chat = update.effective_chat

    if chat.type not in [
        "group",
        "supergroup"
    ]:
        return

    register_chat(chat)

    old_data = get_user(
        user.id,
        chat.id
    )

    old_level = (
        old_data[6]
        if old_data
        else 1
    )

    (
        xp,
        coins,
        messages,
        level,
        streak,
        rating
    ) = add_activity(
        user,
        chat.id
    )

    update_world_progress(
        chat.id
    )

    if level > old_level:

        await update.message.reply_text(
            "━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>LEVEL UP!</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"👤 {user.first_name}\n"
            f"🆙 Level: <b>{level}</b>\n"
            f"🏅 Rank: <b>{get_rank(level)}</b>\n"
            f"⭐ XP: <b>{xp}</b>\n\n"

            "🔥 Keep climbing!",
            parse_mode="HTML"
        )


# =========================================================
# POST INIT
# =========================================================

async def post_init(
    app: Application
):

    asyncio.create_task(
        boss_loop(app)
    )

    asyncio.create_task(
        random_event_loop(app)
    )

    print(
        "Background systems started."
    )


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    if (
        not TOKEN
        or TOKEN == "BU_YERGA_BOT_TOKENINGNI_QOY"
    ):

        print(
            "❌ TOKEN QO‘YILMAGAN!"
        )

        return

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    # COMMANDS

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    app.add_handler(
        CommandHandler(
            "top",
            top
        )
    )

    app.add_handler(
        CommandHandler(
            "bonus",
            bonus
        )
    )

    app.add_handler(
        CommandHandler(
            "quiz",
            quiz
        )
    )

    app.add_handler(
        CommandHandler(
            "world",
            world
        )
    )

    app.add_handler(
        CommandHandler(
            "boss",
            boss
        )
    )

    app.add_handler(
        CommandHandler(
            "attack",
            attack
        )
    )

    app.add_handler(
        CommandHandler(
            "mission",
            mission
        )
    )

    app.add_handler(
        CommandHandler(
            "faction",
            faction
        )
    )

    app.add_handler(
        CommandHandler(
            "activity",
            activity_stats
        )
    )

    app.add_handler(
        CommandHandler(
            "hall",
            hall
        )
    )

    # QUIZ BUTTON

    app.add_handler(
        CallbackQueryHandler(
            quiz_answer,
            pattern=r"^quiz:"
        )
    )

    # FACTION BUTTON

    app.add_handler(
        CallbackQueryHandler(
            faction_answer,
            pattern=r"^faction:"
        )
    )

    # NEW MEMBERS

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome
        )
    )

    # GROUP ACTIVITY

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            activity
        )
    )

    print(
        "======================================"
    )

    print(
        "⚡ MINECRAFT COMMUNITY SYSTEM"
    )

    print(
        "⚔️ FACTIONS"
    )

    print(
        "🌍 COMMUNITY WORLD"
    )

    print(
        "💀 WORLD BOSS"
    )

    print(
        "🏆 BOSS DAMAGE TOP 3"
    )

    print(
        "🎯 SECRET MISSIONS"
    )

    print(
        "🧠 MINECRAFT QUIZ"
    )

    print(
        "🏆 XP / RANK / COINS / RATING"
    )

    print(
        "======================================"
    )

    app.run_polling()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()