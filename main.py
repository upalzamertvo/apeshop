#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vape Shop Telegram Bot v9.2 — Python Edition
+ Отзывы ПОЧИНЕНЫ: writing_review и rate/deal_yes — самые первые проверки
+ Фото товаров (админ отправляет фото при добавлении)
+ Двухшаговое подтверждение сделки (админ → покупатель → отзыв)
+ Удаление заказов и запросов поставки + уведомления
+ Корзина: кнопки +, -, 🗑 исправлены
+ Дублирование заказов исправлено
+ Кол-во пользователей вместо статистики
+ Кэш подписки 5 мин + SQLite WAL

Установка: pip install python-telegram-bot
Запуск: python bot.py
"""

import os
import json
import sqlite3
import logging
import uuid
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ===== Настройки =====
TOKEN = os.environ.get("BOT_TOKEN", "9106749626:AAEPYFwdSZ5itAaHK1KY6gYqMLaedhS9Yao")
DB_PATH = "vape_shop.db"
MAIN_ADMIN_ID = 6827569074
REVIEW_CHANNEL_ID = -1004477314620
REVIEW_CHANNEL_LINK = "https://t.me/jshsdjhe"

CATEGORIES = ["жижки", "подики", "одноразки", "другое"]
CATEGORY_EMOJI = {"жижки": "🧪", "подики": "🔌", "одноразки": "💨", "другое": "📦"}
CATEGORY_LABELS = {"жижки": "Жижки", "подики": "Подики", "одноразки": "Одноразки", "другое": "Другое"}

SAMPLE_PRODUCTS = {
    "жижки": [
        {"name": "Лесные ягоды 60мл", "price": 350, "description": "Освежающий микс лесных ягод, 3 мг"},
        {"name": "Манго-маракуйя 60мл", "price": 400, "description": "Тропический вкус манго и маракуйи, 3 мг"},
        {"name": "Мята-холодок 60мл", "price": 300, "description": "Мятная свежесть с холодком, 3 мг"},
    ],
    "подики": [
        {"name": "XROS 3", "price": 2500, "description": "Под-система с регулировкой обдува, 1000mAh"},
        {"name": "Vaporesso XROS 2", "price": 2200, "description": "Компактная и удобная под-система"},
    ],
    "одноразки": [
        {"name": "Elf Bar 1500", "price": 800, "description": "Одноразка на 1500 затяжек, ассортимент вкусов"},
        {"name": "HQD Cuvie Plus", "price": 600, "description": "Одноразка на 1200 затяжек, ассортимент вкусов"},
    ],
    "другое": [
        {"name": "Койлы (спираль)", "price": 150, "description": "Готовые койлы для обслуживаемых атомайзеров"},
        {"name": "Хлопок органический", "price": 100, "description": "Японский органический хлопок для ваты"},
    ],
}

WELCOME = (
    "🌬️ <b>Добро пожаловать в вейп-шоп!</b>\n\n"
    "Здесь вы можете:\n"
    "🛒 Просмотреть каталог товаров\n"
    "🔍 Найти товар по названию\n"
    "🛍 Собрать корзину и оформить заказ\n"
    "❤️ Сохранять товары в избранное\n"
    "📋 Посмотреть свои заказы\n"
    "📦 Запросить пополнение каталога\n"
    "📞 Обратиться в поддержку\n\n"
    "Выберите раздел в меню 👇"
)

# Кэш проверки подписки: {user_id: (timestamp, result)}
_sub_cache = {}
SUB_CACHE_TTL = 300  # 5 минут

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== База данных =====
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("""CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, name TEXT, price INTEGER, description TEXT, category TEXT)""")
    try:
        cols = c.execute("PRAGMA table_info(reviews)").fetchall()
        if cols and len(cols) != 6:
            c.execute("DROP TABLE reviews")
            c.execute(
                """CREATE TABLE reviews (id TEXT PRIMARY KEY, user_id INTEGER, username TEXT, rating INTEGER, text TEXT, created_at TEXT)""")
    except:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS cart (user_id INTEGER, product_id TEXT, name TEXT, price INTEGER, quantity INTEGER, category TEXT, PRIMARY KEY (user_id, product_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, user_id INTEGER, username TEXT, items TEXT, total_price INTEGER, status TEXT, created_at TEXT, customer_info TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, user_id INTEGER, username TEXT, rating INTEGER, text TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, product_id TEXT, name TEXT, price INTEGER, category TEXT, description TEXT, PRIMARY KEY (user_id, product_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, first_seen TEXT, last_active TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS replenish_reqs (id TEXT PRIMARY KEY, user_id INTEGER, username TEXT, text TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS support_msgs (id TEXT PRIMARY KEY, user_id INTEGER, username TEXT, text TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS fwd_mapping (admin_chat_id INTEGER, admin_message_id INTEGER, user_id INTEGER, PRIMARY KEY (admin_chat_id, admin_message_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS state (user_id INTEGER PRIMARY KEY, state TEXT, data TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_by INTEGER, added_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sub_channels (channel_id TEXT PRIMARY KEY, channel_link TEXT, added_at TEXT)""")
    conn.commit()
    seeded = c.execute("SELECT value FROM settings WHERE key='seeded'").fetchone()
    if not seeded:
        for category, items in SAMPLE_PRODUCTS.items():
            for item in items:
                pid = uuid.uuid4().hex[:8]
                c.execute("INSERT INTO products (id, name, price, description, category, photo_id) VALUES (?,?,?,?,?,?)", (pid, item["name"], item["price"], item["description"], category, None))
        c.execute("INSERT INTO settings VALUES ('seeded','true')")
        conn.commit()
    conn.close()

# ===== Состояния =====
def get_state(user_id):
    conn = get_db()
    row = conn.execute("SELECT state, data FROM state WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        return {"state": row["state"], "data": json.loads(row["data"]) if row["data"] else {}}
    return {"state": "idle", "data": {}}

def set_state(user_id, state, data=None):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO state (user_id, state, data) VALUES (?,?,?)", (user_id, state, json.dumps(data or {})))
    conn.commit(); conn.close()

def clear_state(user_id):
    set_state(user_id, "idle", {})

# ===== Товары =====
def get_products(category):
    conn = get_db(); rows = conn.execute("SELECT * FROM products WHERE category=?", (category,)).fetchall(); conn.close()
    return [dict(r) for r in rows]

def get_product(category, product_id):
    conn = get_db(); row = conn.execute("SELECT * FROM products WHERE id=? AND category=?", (product_id, category)).fetchone(); conn.close()
    return dict(row) if row else None

def add_product_db(name, price, description, category, photo_id=None):
    conn = get_db(); pid = uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO products (id, name, price, description, category, photo_id) VALUES (?,?,?,?,?,?)", (pid, name, price, description, category, photo_id))
    conn.commit(); conn.close()

def delete_product_db(category, product_id):
    conn = get_db(); conn.execute("DELETE FROM products WHERE id=? AND category=?", (product_id, category))
    conn.commit(); conn.close()

def search_products(query):
    conn = get_db(); q = f"%{query.lower()}%"
    rows = conn.execute("SELECT * FROM products WHERE LOWER(name) LIKE ? OR LOWER(description) LIKE ?", (q, q)).fetchall()
    conn.close(); return [dict(r) for r in rows]

# ===== Избранное =====
def get_favorites(user_id):
    conn = get_db(); rows = conn.execute("SELECT * FROM favorites WHERE user_id=?", (user_id,)).fetchall(); conn.close()
    return [dict(r) for r in rows]

def toggle_favorite(user_id, product):
    conn = get_db()
    existing = conn.execute("SELECT * FROM favorites WHERE user_id=? AND product_id=?", (user_id, product["id"])).fetchone()
    if existing:
        conn.execute("DELETE FROM favorites WHERE user_id=? AND product_id=?", (user_id, product["id"]))
        conn.commit(); conn.close(); return False
    else:
        conn.execute("INSERT INTO favorites VALUES (?,?,?,?,?,?)", (user_id, product["id"], product["name"], product["price"], product["category"], product["description"]))
        conn.commit(); conn.close(); return True

def is_favorite(user_id, product_id):
    conn = get_db(); row = conn.execute("SELECT 1 FROM favorites WHERE user_id=? AND product_id=?", (user_id, product_id)).fetchone(); conn.close()
    return row is not None

def clear_favorites(user_id):
    conn = get_db(); conn.execute("DELETE FROM favorites WHERE user_id=?", (user_id,)); conn.commit(); conn.close()

# ===== Корзина =====
def get_cart(user_id):
    conn = get_db(); rows = conn.execute("SELECT * FROM cart WHERE user_id=?", (user_id,)).fetchall(); conn.close()
    return [dict(r) for r in rows]

def add_to_cart(user_id, product):
    conn = get_db()
    existing = conn.execute("SELECT * FROM cart WHERE user_id=? AND product_id=?", (user_id, product["id"])).fetchone()
    if existing:
        conn.execute("UPDATE cart SET quantity=quantity+1 WHERE user_id=? AND product_id=?", (user_id, product["id"]))
    else:
        conn.execute("INSERT INTO cart VALUES (?,?,?,?,?,?)", (user_id, product["id"], product["name"], product["price"], 1, product["category"]))
    conn.commit(); conn.close()

def remove_from_cart(user_id, product_id):
    conn = get_db(); conn.execute("DELETE FROM cart WHERE user_id=? AND product_id=?", (user_id, product_id)); conn.commit(); conn.close()

def change_cart_quantity(user_id, product_id, delta):
    conn = get_db()
    item = conn.execute("SELECT * FROM cart WHERE user_id=? AND product_id=?", (user_id, product_id)).fetchone()
    if not item: conn.close(); return
    new_qty = item["quantity"] + delta
    if new_qty <= 0:
        conn.execute("DELETE FROM cart WHERE user_id=? AND product_id=?", (user_id, product_id))
    else:
        conn.execute("UPDATE cart SET quantity=? WHERE user_id=? AND product_id=?", (new_qty, user_id, product_id))
    conn.commit(); conn.close()

def clear_cart(user_id):
    conn = get_db(); conn.execute("DELETE FROM cart WHERE user_id=?", (user_id,)); conn.commit(); conn.close()

# ===== Заказы =====
def get_all_orders():
    conn = get_db(); rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]

def get_order(order_id):
    conn = get_db(); row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone(); conn.close()
    return dict(row) if row else None

def add_order_db(order_id, user_id, username, items, total_price, customer_info):
    conn = get_db()
    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", (order_id, user_id, username, json.dumps(items), total_price, "pending", datetime.now().isoformat(), customer_info))
    conn.commit(); conn.close()

def update_order_status(order_id, status):
    conn = get_db(); conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id)); conn.commit(); conn.close()

def delete_order(order_id):
    conn = get_db(); conn.execute("DELETE FROM orders WHERE id=?", (order_id,)); conn.commit(); conn.close()

def get_orders_by_user(user_id):
    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE user_id=? AND status != 'cancelled' ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close(); return [dict(r) for r in rows]

# ===== Отзывы (о сервисе/магазине, не о товарах) =====
def get_reviews():
    conn = get_db(); rows = conn.execute("SELECT * FROM reviews ORDER BY created_at DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]

def add_review_db(user_id, username, rating, text):
    conn = get_db(); rid = uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?)", (rid, user_id, username, rating, text, datetime.now().isoformat()))
    conn.commit(); conn.close()

# ===== Пользователи =====
def store_user(user):
    conn = get_db()
    existing = conn.execute("SELECT * FROM users WHERE id=?", (user.id,)).fetchone()
    if existing:
        conn.execute("UPDATE users SET username=?, first_name=?, last_active=? WHERE id=?", (user.username, user.first_name, datetime.now().isoformat(), user.id))
    else:
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?)", (user.id, user.username, user.first_name, datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit(); conn.close()

def get_user(user_id):
    conn = get_db(); row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone(); conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = get_db(); rows = conn.execute("SELECT * FROM users ORDER BY last_active DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]

# ===== Админы =====
def get_admins():
    conn = get_db(); rows = conn.execute("SELECT * FROM admins").fetchall(); conn.close()
    return [dict(r) for r in rows]

def add_admin(user_id, added_by):
    conn = get_db(); conn.execute("INSERT OR IGNORE INTO admins VALUES (?,?,?)", (user_id, added_by, datetime.now().isoformat())); conn.commit(); conn.close()

def remove_admin(user_id):
    conn = get_db(); conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,)); conn.commit(); conn.close()

def is_admin(user_id):
    if user_id == MAIN_ADMIN_ID: return True
    conn = get_db(); row = conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone(); conn.close()
    return row is not None

# ===== Каналы подписки =====
def get_sub_channels():
    conn = get_db(); rows = conn.execute("SELECT * FROM sub_channels ORDER BY added_at DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]

def add_sub_channel(channel_id, channel_link):
    conn = get_db(); conn.execute("INSERT OR REPLACE INTO sub_channels VALUES (?,?,?)", (channel_id, channel_link, datetime.now().isoformat())); conn.commit(); conn.close()

def remove_sub_channel(channel_id):
    conn = get_db(); conn.execute("DELETE FROM sub_channels WHERE channel_id=?", (channel_id,)); conn.commit(); conn.close()

# ===== Запросы и поддержка =====
def add_replenish_req(user_id, username, text):
    conn = get_db(); rid = uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO replenish_reqs VALUES (?,?,?,?,?)", (rid, user_id, username, text, datetime.now().isoformat()))
    conn.commit(); conn.close()

def get_replenish_reqs():
    conn = get_db(); rows = conn.execute("SELECT * FROM replenish_reqs ORDER BY created_at DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]

def delete_replenish_req(req_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM replenish_reqs WHERE id=?", (req_id,)).fetchone()
    conn.execute("DELETE FROM replenish_reqs WHERE id=?", (req_id,))
    conn.commit(); conn.close()
    return dict(row) if row else None

def add_support_msg(user_id, username, text):
    conn = get_db(); rid = uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO support_msgs VALUES (?,?,?,?,?)", (rid, user_id, username, text, datetime.now().isoformat()))
    conn.commit(); conn.close()

def get_support_msgs():
    conn = get_db(); rows = conn.execute("SELECT * FROM support_msgs ORDER BY created_at DESC").fetchall(); conn.close()
    return [dict(r) for r in rows]

# ===== Fwd mapping =====
def set_fwd_mapping(admin_chat_id, admin_message_id, user_id):
    conn = get_db(); conn.execute("INSERT OR REPLACE INTO fwd_mapping VALUES (?,?,?)", (admin_chat_id, admin_message_id, user_id)); conn.commit(); conn.close()

def get_fwd_mapping(admin_chat_id, admin_message_id):
    conn = get_db(); row = conn.execute("SELECT user_id FROM fwd_mapping WHERE admin_chat_id=? AND admin_message_id=?", (admin_chat_id, admin_message_id)).fetchone(); conn.close()
    return row["user_id"] if row else None

# ===== Проверка подписки (с кэшем 5 мин) =====
async def check_subscription(context, user_id):
    channels = get_sub_channels()
    if not channels: return True
    cached = _sub_cache.get(user_id)
    if cached and (time.time() - cached[0]) < SUB_CACHE_TTL:
        return cached[1]
    result = True
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                result = False
                break
        except:
            result = False
            break
    _sub_cache[user_id] = (time.time(), result)
    return result

def subscription_kb():
    channels = get_sub_channels()
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton("📢 Подписаться", url=ch["channel_link"])])
    rows.append([InlineKeyboardButton("✅ Я подписался, проверить", callback_data="check_sub")])
    return InlineKeyboardMarkup(rows)

# ===== Хелперы для отображения =====
def cart_text(cart):
    if not cart:
        return "🛍 <b>Корзина пуста</b>"
    items_text = "\n".join(f"• {i['name']} x{i['quantity']} = {i['price']*i['quantity']}₽" for i in cart)
    total = sum(i["price"]*i["quantity"] for i in cart)
    return f"🛍 <b>Корзина</b>\n\n{items_text}\n\n💰 {total}₽"

def build_order_text(order):
    items = json.loads(order["items"])
    items_text = "\n".join(f"{i+1}. {item['name']} x{item['quantity']} = {item['price']*item['quantity']}₽" for i, item in enumerate(items))
    sl = {"pending":"⏳ Ожидает","confirmed":"🔔 Подтверждён администратором","completed":"✅ Выполнен","cancelled":"❌ Отменён"}
    return (f"🆕 <b>#{order['id']}</b>\n\n👤 @{order['username']} (ID: {order['user_id']})\n"
            f"📍 {order['customer_info']}\n\n📦 {items_text}\n\n💰 {order['total_price']}₽\n\n{sl.get(order['status'],order['status'])}")

def admin_panel_text():
    user_count = len(get_all_users())
    return f"🔧 <b>Панель администратора</b>\n\n👥 Активных пользователей: <b>{user_count}</b>"

def product_text(product):
    return f"🛒 <b>{product['name']}</b>\n\n💰 {product['price']}₽\n📝 {product['description']}"

async def show_product(query, context, chat_id, category, product, is_fav):
    text = product_text(product)
    kb = product_kb(category, product["id"], is_fav)
    has_photo = bool(product.get("photo_id"))
    msg_is_photo = bool(query.message.photo)
    if has_photo and msg_is_photo:
        await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=kb)
    elif has_photo and not msg_is_photo:
        try: await query.message.delete()
        except: pass
        await context.bot.send_photo(chat_id, photo=product["photo_id"], caption=text, parse_mode="HTML", reply_markup=kb)
    elif not has_photo and msg_is_photo:
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
    else:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

async def edit_or_replace(query, context, chat_id, text, reply_markup):
    if query.message.photo:
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

# ===== Клавиатуры клиента =====
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Каталог", callback_data="catalog"),
         InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("🛍 Корзина", callback_data="cart"),
         InlineKeyboardButton("❤️ Избранное", callback_data="favorites")],
        [InlineKeyboardButton("📋 Мои заказы", callback_data="myorders")],
        [InlineKeyboardButton("📦 Пополнить каталог", callback_data="replenish"),
         InlineKeyboardButton("📞 Поддержка", callback_data="support")],
        [InlineKeyboardButton("⭐ Отзывы", url=REVIEW_CHANNEL_LINK)],
    ])

def catalog_kb():
    rows = [[InlineKeyboardButton(f"{CATEGORY_EMOJI[c]} {CATEGORY_LABELS[c]}", callback_data=f"cat:{c}")] for c in CATEGORIES]
    rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def category_kb(category, products):
    rows = [[InlineKeyboardButton(f"{p['name']} — {p['price']}₽", callback_data=f"prod:{category}:{p['id']}")] for p in products]
    rows.append([InlineKeyboardButton("⬅️ К категориям", callback_data="catalog")])
    return InlineKeyboardMarkup(rows)

def product_kb(category, product_id, is_fav):
    fav_btn = (InlineKeyboardButton("❤️ В избранном", callback_data=f"fav_toggle:{category}:{product_id}")
               if is_fav else InlineKeyboardButton("🤍 В избранное", callback_data=f"fav_toggle:{category}:{product_id}"))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ В корзину", callback_data=f"add:{category}:{product_id}"), fav_btn],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"cat:{category}")],
    ])

def cart_kb(cart):
    rows = []
    for item in cart:
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"cart_dec:{item['product_id']}"),
            InlineKeyboardButton(f"{item['name']} x{item['quantity']} = {item['price']*item['quantity']}₽", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart_inc:{item['product_id']}"),
            InlineKeyboardButton("🗑", callback_data=f"cart_rm:{item['product_id']}"),
        ])
    if cart:
        rows.append([InlineKeyboardButton("✅ Оформить заказ", callback_data="checkout")])
        rows.append([InlineKeyboardButton("🗑 Очистить корзину", callback_data="cart_clear")])
    rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def favorites_kb(favs):
    rows = [[InlineKeyboardButton(f"{f['name']} — {f['price']}₽", callback_data=f"prod:{f['category']}:{f['product_id']}")] for f in favs]
    if favs:
        rows.append([InlineKeyboardButton("🛒 Всё в корзину", callback_data="fav_all_cart")])
        rows.append([InlineKeyboardButton("🗑 Очистить избранное", callback_data="fav_clear")])
    rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def search_results_kb(results):
    rows = [[InlineKeyboardButton(f"{p['name']} — {p['price']}₽", callback_data=f"prod:{p['category']}:{p['id']}")] for p in results[:20]]
    rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def my_orders_kb(orders):
    status_emoji = {"completed": "✅", "confirmed": "🔔", "pending": "⏳"}
    rows = [[InlineKeyboardButton(f"{status_emoji.get(o['status'],'⏳')} #{o['id']} — {o['total_price']}₽", callback_data=f"myorder:{o['id']}")] for o in orders[:10]]
    rows.append([InlineKeyboardButton("⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def deal_confirm_kb(order_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да, получил", callback_data=f"deal_yes:{order_id}"), InlineKeyboardButton("❌ Нет", callback_data=f"deal_no:{order_id}")]])

def rating_kb(order_id):
    rows = []
    for i in range(1, 11):
        rows.append([InlineKeyboardButton(f"{'⭐'*min(i,5)} {i}/10", callback_data=f"rate:{i}:{order_id}")])
    rows.append([InlineKeyboardButton("⬅️ Пропустить", callback_data="rev_skip")])
    return InlineKeyboardMarkup(rows)

# ===== Клавиатуры админа =====
def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить товар", callback_data="admin_add"),
         InlineKeyboardButton("🗑 Удалить товар", callback_data="admin_del")],
        [InlineKeyboardButton("📋 Заказы", callback_data="admin_orders")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📦 Запросы поставки", callback_data="admin_replenish"),
         InlineKeyboardButton("📞 Обращения поддержки", callback_data="admin_support")],
        [InlineKeyboardButton("👥 Клиенты", callback_data="admin_users")],
        [InlineKeyboardButton("🔐 Админы", callback_data="admin_admins"),
         InlineKeyboardButton("📢 Каналы подписки", callback_data="admin_channels")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="menu")],
    ])

def admin_add_cat_kb():
    rows = [[InlineKeyboardButton(f"{CATEGORY_EMOJI[c]} {CATEGORY_LABELS[c]}", callback_data=f"admin_addcat:{c}")] for c in CATEGORIES]
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def admin_del_cat_kb():
    rows = [[InlineKeyboardButton(f"{CATEGORY_EMOJI[c]} {CATEGORY_LABELS[c]}", callback_data=f"admin_delcat:{c}")] for c in CATEGORIES]
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def admin_del_prod_kb(category, products):
    rows = [[InlineKeyboardButton(f"🗑 {p['name']} — {p['price']}₽", callback_data=f"admin_delprod:{category}:{p['id']}")] for p in products]
    rows.append([InlineKeyboardButton("⬅️ К категориям", callback_data="admin_del")])
    return InlineKeyboardMarkup(rows)

def admin_orders_list_kb(orders):
    se = {"completed": "✅", "cancelled": "❌", "confirmed": "🔔", "pending": "⏳"}
    rows = [[InlineKeyboardButton(f"{se.get(o['status'],'⏳')} #{o['id']} — @{o['username']} — {o['total_price']}₽ — {o['status']}", callback_data=f"admin_order_view:{o['id']}")] for o in orders]
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def admin_order_detail_kb(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"admin_confirm:{order_id}"),
         InlineKeyboardButton("❌ Отменить", callback_data=f"admin_cancel:{order_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_order:{order_id}")],
        [InlineKeyboardButton("👤 Профиль клиента", callback_data=f"admin_user_from_order:{order_id}")],
        [InlineKeyboardButton("⬅️ К списку заказов", callback_data="admin_orders")],
    ])

def forwarded_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Профиль клиента", callback_data=f"admin_user:{user_id}"),
         InlineKeyboardButton("💬 Написать клиенту", callback_data=f"admin_msg:{user_id}")],
    ])

def user_profile_kb(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Написать клиенту", callback_data=f"admin_msg:{user_id}")],
        [InlineKeyboardButton("⬅️ В админку", callback_data="admin")],
    ])

def users_list_kb(users):
    rows = []
    for u in users[:20]:
        name = f"@{u['username']}" if u["username"] else u["first_name"] or f"ID:{u['id']}"
        rows.append([InlineKeyboardButton(name, callback_data=f"admin_user:{u['id']}")])
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def admin_list_kb(admins):
    rows = []
    for a in admins:
        if a["user_id"] != MAIN_ADMIN_ID:
            rows.append([InlineKeyboardButton(f"🗑 {a['user_id']}", callback_data=f"admin_rm_admin:{a['user_id']}")])
    rows.append([InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_admin")])
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def sub_channels_kb(channels):
    rows = []
    for ch in channels:
        rows.append([InlineKeyboardButton(f"🗑 {ch['channel_link']}", callback_data=f"admin_rm_channel:{ch['channel_id']}")])
    rows.append([InlineKeyboardButton("➕ Добавить канал", callback_data="admin_add_channel")])
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def replenish_list_kb(reqs):
    rows = [[InlineKeyboardButton(f"📦 @{r['username']} — {r['text'][:30]}", callback_data=f"admin_replenish_view:{r['id']}")] for r in reqs[:10]]
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def replenish_detail_kb(req_id, user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Выполнено", callback_data=f"admin_replenish_done:{req_id}:{user_id}"),
         InlineKeyboardButton("❌ Нет", callback_data=f"admin_replenish_no:{req_id}:{user_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_replenish_del:{req_id}")],
        [InlineKeyboardButton("👤 Профиль", callback_data=f"admin_user:{user_id}"),
         InlineKeyboardButton("💬 Написать", callback_data=f"admin_msg:{user_id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data="admin_replenish")],
    ])

def support_list_kb(msgs):
    rows = [[InlineKeyboardButton(f"📞 @{m['username']} — {m['text'][:30]}", callback_data=f"admin_support_view:{m['id']}")] for m in msgs[:10]]
    rows.append([InlineKeyboardButton("⬅️ В админку", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def support_detail_kb(msg_id, user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Профиль", callback_data=f"admin_user:{user_id}"),
         InlineKeyboardButton("💬 Написать", callback_data=f"admin_msg:{user_id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data="admin_support")],
    ])

# ===== Команды =====
async def cmd_start(update, context):
    store_user(update.effective_user)
    clear_state(update.effective_user.id)
    is_subscribed = await check_subscription(context, update.effective_user.id)
    if not is_subscribed:
        await update.message.reply_text("🔒 <b>Для использования бота подпишитесь на наш канал!</b>\n\nПосле подписки нажмите «Проверить».", parse_mode="HTML", reply_markup=subscription_kb())
        return
    await update.message.reply_text(WELCOME, parse_mode="HTML", reply_markup=main_menu_kb())

async def cmd_admin(update, context):
    store_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа к админ-панели.")
        return
    await update.message.reply_text(admin_panel_text(), parse_mode="HTML", reply_markup=admin_kb())

# ===== Обработка фото (админ добавляет фото товара) =====
async def handle_photo(update, context):
    user = update.effective_user
    store_user(user)
    admin = is_admin(user.id)
    state = get_state(user.id)

    if admin and state["state"] == "admin_add_photo":
        photo = update.message.photo[-1]
        file_id = photo.file_id
        data = state["data"]
        add_product_db(data["name"], data["price"], data["description"], data["category"], file_id)
        await update.message.reply_text(
            f"✅ Добавлен с фото!\n{CATEGORY_EMOJI[data['category']]} {data['name']} — {data['price']}₽\n{data['description']}",
            reply_markup=admin_kb()
        )
        clear_state(user.id)
        return

    if admin:
        await update.message.reply_text("Используйте /admin", reply_markup=main_menu_kb())

# ===== Текстовые сообщения =====
async def handle_message(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    username = user.username or user.first_name
    store_user(user)
    admin = is_admin(user.id)
    state = get_state(user.id)

    # ОТЛАДКА — покажет в консоли что происходит
    logger.info(f"handle_message: user={user.id} admin={admin} state={state['state']} text={text[:50]}")

    # ================================================================
    # ОТЗЫВ — САМАЯ ПЕРВАЯ ПРОВЕРКА, ДО АДМИНА И ДО ПОДПИСКИ
    # ================================================================
    if state["state"] == "writing_review":
        data = state["data"]
        logger.info(f"Отзыв получен: rating={data.get('rating')} от user={user.id}")
        review_text = text if text != "-" else "Без текста"
        add_review_db(user.id, username, data["rating"], review_text)
        try:
            channel_text = (f"⭐ <b>Новый отзыв о сервисе!</b>\n\n👤 Пользователь: @{username}\n⭐ Оценка: {data['rating']}/10\n{'⭐' * data['rating']}\n\n💬 {review_text}")
            await context.bot.send_message(REVIEW_CHANNEL_ID, channel_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить отзыв в канал: {e}")
        await update.message.reply_text("✅ Спасибо за отзыв!", reply_markup=main_menu_kb())
        clear_state(user.id); return

    # Админ отвечает на пересланное сообщение (reply)
    if admin and update.message.reply_to_message:
        target_uid = get_fwd_mapping(chat_id, update.message.reply_to_message.message_id)
        if target_uid:
            await context.bot.send_message(target_uid, f"💬 <b>Ответ от администратора:</b>\n\n{text}", parse_mode="HTML")
            await update.message.reply_text("✅ Ответ отправлен клиенту.")
            return

    if admin:
        await handle_admin_message(update, context)
        return

    # Проверка подписки — только для обычных пользователей
    if not admin:
        is_subscribed = await check_subscription(context, user.id)
        if not is_subscribed:
            await update.message.reply_text("🔒 Подпишитесь на канал!", reply_markup=subscription_kb())
            return

    if state["state"] == "support":
        add_support_msg(user.id, username, text)
        notify_ids = [a["user_id"] for a in get_admins()] + ([MAIN_ADMIN_ID] if MAIN_ADMIN_ID else [])
        for aid in set(notify_ids):
            try:
                msg = await context.bot.send_message(aid, f"📞 <b>Обращение в поддержку</b>\nОт: @{username} (ID: {user.id})\n\n{text}", parse_mode="HTML", reply_markup=forwarded_kb(user.id))
                set_fwd_mapping(aid, msg.message_id, user.id)
            except: pass
        await update.message.reply_text("✅ Сообщение отправлено в поддержку.", reply_markup=main_menu_kb())
        clear_state(user.id); return

    if state["state"] == "replenishment":
        add_replenish_req(user.id, username, text)
        notify_ids = [a["user_id"] for a in get_admins()] + ([MAIN_ADMIN_ID] if MAIN_ADMIN_ID else [])
        for aid in set(notify_ids):
            try:
                msg = await context.bot.send_message(aid, f"📦 <b>Запрос на поставку</b>\nОт: @{username} (ID: {user.id})\n\n{text}", parse_mode="HTML", reply_markup=forwarded_kb(user.id))
                set_fwd_mapping(aid, msg.message_id, user.id)
            except: pass
        await update.message.reply_text("✅ Запрос отправлен.", reply_markup=main_menu_kb())
        clear_state(user.id); return

    if state["state"] == "search":
        results = search_products(text)
        if not results:
            await update.message.reply_text("🔍 Ничего не найдено.", reply_markup=main_menu_kb())
        else:
            await update.message.reply_text(f"🔍 <b>Результаты</b> ({len(results)})", parse_mode="HTML", reply_markup=search_results_kb(results))
        clear_state(user.id); return

    if state["state"] == "checkout":
        # ОЧИЩАЕМ СОСТОЯНИЕ ПЕРВЫМ — чтобы предотвратить дублирование заказа
        clear_state(user.id)
        cart = get_cart(user.id)
        if not cart:
            await update.message.reply_text("Корзина пуста!", reply_markup=main_menu_kb())
            return
        total = sum(i["price"] * i["quantity"] for i in cart)
        order_id = uuid.uuid4().hex[:8]
        add_order_db(order_id, user.id, username, cart, total, text)
        items_text = "\n".join(f"{i+1}. {item['name']} x{item['quantity']} = {item['price']*item['quantity']}₽" for i, item in enumerate(cart))
        order_text = f"🆕 <b>Новый заказ #{order_id}</b>\n\n👤 Клиент: @{username} (ID: {user.id})\n📍 Встреча: {text}\n\n📦 <b>Товары:</b>\n{items_text}\n\n💰 <b>Итого: {total}₽</b>\n\nСтатус: ⏳ Ожидает подтверждения"
        notify_ids = [a["user_id"] for a in get_admins()] + ([MAIN_ADMIN_ID] if MAIN_ADMIN_ID else [])
        for aid in set(notify_ids):
            try:
                await context.bot.send_message(aid, order_text, parse_mode="HTML", reply_markup=admin_order_detail_kb(order_id))
            except: pass
        await update.message.reply_text(f"✅ Заявка оформлена! №{order_id}\n\n📍 Встреча: {text}\n\nАдминистратор свяжется с вами.", reply_markup=main_menu_kb())
        clear_cart(user.id); return

    await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu_kb())

async def handle_admin_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text or ""
    state = get_state(user_id)

    # ОТЛАДКА
    logger.info(f"handle_admin_message: user={user_id} state={state['state']} text={text[:50]}")

    # ОТЗЫВ — проверяем и здесь (если админ тестирует отзывы)
    if state["state"] == "writing_review":
        data = state["data"]
        username = update.effective_user.username or update.effective_user.first_name
        review_text = text if text != "-" else "Без текста"
        add_review_db(user_id, username, data["rating"], review_text)
        try:
            channel_text = (f"⭐ <b>Новый отзыв о сервисе!</b>\n\n👤 Пользователь: @{username}\n⭐ Оценка: {data['rating']}/10\n{'⭐' * data['rating']}\n\n💬 {review_text}")
            await context.bot.send_message(REVIEW_CHANNEL_ID, channel_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить отзыв в канал: {e}")
        await update.message.reply_text("✅ Спасибо за отзыв!", reply_markup=main_menu_kb())
        clear_state(user_id); return

    if state["state"].startswith("admin_msg_user:"):
        target_uid = int(state["state"].split(":")[1])
        await context.bot.send_message(target_uid, f"💬 <b>Сообщение от администратора:</b>\n\n{text}", parse_mode="HTML")
        await update.message.reply_text("✅ Отправлено клиенту.", reply_markup=admin_kb())
        clear_state(user_id); return

    if state["state"] == "admin_broadcast":
        users = get_all_users()
        sent, failed = 0, 0
        for u in users:
            try:
                await context.bot.send_message(u["id"], f"📢 <b>Сообщение от магазина:</b>\n\n{text}", parse_mode="HTML")
                sent += 1
            except: failed += 1
        await update.message.reply_text(f"📢 Готово!\n✅ {sent}\n❌ {failed}", reply_markup=admin_kb())
        clear_state(user_id); return

    if state["state"] == "admin_add_name":
        set_state(user_id, "admin_add_price", {"category": state["data"]["category"], "name": text})
        await update.message.reply_text(f"Цена для «{text}» (число):"); return

    if state["state"] == "admin_add_price":
        try: price = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ Число:"); return
        data = state["data"]
        set_state(user_id, "admin_add_desc", {"category": data["category"], "name": data["name"], "price": price})
        await update.message.reply_text("Описание товара:"); return

    if state["state"] == "admin_add_desc":
        data = state["data"]
        set_state(user_id, "admin_add_photo", {"category": data["category"], "name": data["name"], "price": data["price"], "description": text})
        await update.message.reply_text("📷 Отправьте фото товара (или напишите «-» чтобы пропустить):"); return

    if state["state"] == "admin_add_photo":
        if text == "-":
            data = state["data"]
            add_product_db(data["name"], data["price"], data["description"], data["category"], None)
            await update.message.reply_text(f"✅ Добавлен!\n{CATEGORY_EMOJI[data['category']]} {data['name']} — {data['price']}₽\n{data['description']}", reply_markup=admin_kb())
            clear_state(user_id); return
        else:
            await update.message.reply_text("📷 Отправьте фото или напишите «-»:")
            return

    if state["state"] == "admin_add_admin_id":
        try:
            new_admin_id = int(text)
            add_admin(new_admin_id, user_id)
            await update.message.reply_text(f"✅ Админ {new_admin_id} добавлен!", reply_markup=admin_kb())
        except ValueError:
            await update.message.reply_text("⚠️ Введите числовой ID:", reply_markup=admin_kb())
        clear_state(user_id); return

    if state["state"] == "admin_add_channel":
        parts = text.split("|")
        if len(parts) == 2:
            ch_id = parts[0].strip(); ch_link = parts[1].strip()
            add_sub_channel(ch_id, ch_link)
            await update.message.reply_text(f"✅ Канал добавлен!\nID: {ch_id}\nСсылка: {ch_link}", reply_markup=admin_kb())
        else:
            await update.message.reply_text("⚠️ Формат: ID|ссылка\nНапример: -1001234567890|https://t.me/mychannel", reply_markup=admin_kb())
        clear_state(user_id); return

    await update.message.reply_text("Используйте /admin", reply_markup=main_menu_kb())

# ===== Callback =====
async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    message_id = query.message.message_id
    data = query.data
    username = query.from_user.username or query.from_user.first_name
    admin = is_admin(user_id)

    if data == "noop": return

    if data == "check_sub":
        if await check_subscription(context, user_id):
            await query.edit_message_text(WELCOME, parse_mode="HTML", reply_markup=main_menu_kb())
        else:
            await query.answer("❌ Вы ещё не подписались!", show_alert=True)
        return

    # ================================================================
    # ОТЗЫВ И ПОДТВЕРЖДЕНИЕ СДЕЛКИ — ПЕРВЫМИ, БЕЗ ПРОВЕРКИ ПОДПИСКИ
    # ================================================================

    # Покупатель подтвердил получение -> показ оценки
    if data.startswith("deal_yes:"):
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order or order["user_id"] != user_id: return
        update_order_status(order_id, "completed")
        await query.edit_message_text("🎉 Спасибо за подтверждение!\n\nПожалуйста, оцените наш сервис от 1 до 10:", reply_markup=rating_kb(order_id))
        return

    # Покупатель выбрал оценку -> просим текст отзыва
    if data.startswith("rate:"):
        parts = data.split(":")
        rating = int(parts[1]); order_id = parts[2]
        if not (1 <= rating <= 10): return
        set_state(user_id, "writing_review", {"rating": rating, "order_id": order_id})
        logger.info(f"rate: установлен state=writing_review для user={user_id} rating={rating}")
        await context.bot.send_message(chat_id, f"Вы поставили {'⭐'*min(rating,5)} {rating}/10.\n\nНапишите текст отзыва (или «-» чтобы пропустить):")
        return

    # Пропустить отзыв
    if data == "rev_skip":
        clear_state(user_id)
        await query.edit_message_text("👌 Без проблем! Спасибо за покупку!", reply_markup=main_menu_kb())
        return

    # Покупатель не получил -> отмена
    if data.startswith("deal_no:"):
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order or order["user_id"] != user_id: return
        update_order_status(order_id, "cancelled")
        delete_order(order_id)
        notify_ids = [a["user_id"] for a in get_admins()] + ([MAIN_ADMIN_ID] if MAIN_ADMIN_ID else [])
        for aid in set(notify_ids):
            try:
                await context.bot.send_message(aid, f"⚠️ @{username}: сделка #{order_id} не состоялась.")
            except: pass
        await context.bot.send_message(chat_id, "Администратор уведомлён.", reply_markup=main_menu_kb())
        return

    # ================================================================
    # ПРОВЕРКА ПОДПИСКИ — только для остальных кнопок
    # ================================================================
    if not admin:
        if not await check_subscription(context, user_id):
            await query.answer("🔒 Сначала подпишитесь на канал!", show_alert=True)
            return

    # ===== Обычные кнопки =====
    if data == "menu":
        clear_state(user_id)
        await edit_or_replace(query, context, chat_id, WELCOME, main_menu_kb()); return
    if data == "catalog":
        await edit_or_replace(query, context, chat_id, "🛒 <b>Каталог</b>", catalog_kb()); return
    if data == "search":
        set_state(user_id, "search", {})
        await context.bot.send_message(chat_id, "🔍 Введите название товара:"); return
    if data == "favorites":
        favs = get_favorites(user_id)
        if not favs:
            await edit_or_replace(query, context, chat_id, "❤️ Пусто.", main_menu_kb()); return
        await edit_or_replace(query, context, chat_id, "❤️ <b>Избранное</b>", favorites_kb(favs)); return
    if data.startswith("fav_toggle:"):
        parts = data.split(":")
        product = get_product(parts[1], parts[2])
        if not product: return
        added = toggle_favorite(user_id, product)
        await query.answer("❤️ Добавлено" if added else "💔 Убрано")
        is_fav = is_favorite(user_id, product["id"])
        await show_product(query, context, chat_id, parts[1], product, is_fav); return
    if data == "fav_all_cart":
        favs = get_favorites(user_id)
        for f in favs:
            product = get_product(f["category"], f["product_id"])
            if product: add_to_cart(user_id, product)
        await context.bot.send_message(chat_id, f"✅ {len(favs)} в корзине!"); return
    if data == "fav_clear":
        clear_favorites(user_id)
        await edit_or_replace(query, context, chat_id, "❤️ Очищено.", favorites_kb([])); return
    if data == "myorders":
        orders = get_orders_by_user(user_id)
        if not orders:
            await edit_or_replace(query, context, chat_id, "📋 Пусто.", main_menu_kb()); return
        labels = {"pending":"⏳","confirmed":"🔔","completed":"✅"}
        text = "📋 <b>Мои заказы</b>\n\n" + "\n".join(f"#{o['id']} — {o['total_price']}₽ — {labels.get(o['status'],o['status'])}" for o in orders[:10])
        await edit_or_replace(query, context, chat_id, text, my_orders_kb(orders)); return
    if data.startswith("myorder:"):
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order or order["user_id"] != user_id: return
        labels = {"pending":"⏳ Ожидает","confirmed":"🔔 Подтверждён","completed":"✅ Выполнен"}
        items = json.loads(order["items"])
        items_text = "\n".join(f"• {i['name']} x{i['quantity']} = {i['price']*i['quantity']}₽" for i in items)
        text = f"📋 <b>#{order['id']}</b>\n\n{labels.get(order['status'],order['status'])}\n📍 {order['customer_info']}\n\n{items_text}\n\n💰 {order['total_price']}₽"
        await edit_or_replace(query, context, chat_id, text, main_menu_kb()); return
    if data.startswith("cat:"):
        category = data.split(":",1)[1]
        products = get_products(category)
        if not products:
            await edit_or_replace(query, context, chat_id, f"{CATEGORY_EMOJI[category]} Пусто.", catalog_kb()); return
        await edit_or_replace(query, context, chat_id, f"{CATEGORY_EMOJI[category]} <b>{CATEGORY_LABELS[category]}</b>", category_kb(category, products)); return
    if data.startswith("prod:"):
        parts = data.split(":")
        product = get_product(parts[1], parts[2])
        if not product:
            await edit_or_replace(query, context, chat_id, "Не найдено.", catalog_kb()); return
        is_fav = is_favorite(user_id, product["id"])
        await show_product(query, context, chat_id, parts[1], product, is_fav); return
    if data.startswith("add:"):
        parts = data.split(":")
        product = get_product(parts[1], parts[2])
        if product:
            add_to_cart(user_id, product)
            await context.bot.send_message(chat_id, f"✅ «{product['name']}» в корзине!"); return
    if data == "cart":
        cart = get_cart(user_id)
        await edit_or_replace(query, context, chat_id, cart_text(cart), cart_kb(cart)); return
    if data.startswith("cart_inc:") or data.startswith("cart_dec:"):
        pid = data.split(":", 1)[1]
        delta = 1 if data.startswith("cart_inc") else -1
        change_cart_quantity(user_id, pid, delta)
        cart = get_cart(user_id)
        await edit_or_replace(query, context, chat_id, cart_text(cart), cart_kb(cart)); return
    if data.startswith("cart_rm:"):
        pid = data.split(":", 1)[1]
        remove_from_cart(user_id, pid)
        cart = get_cart(user_id)
        await edit_or_replace(query, context, chat_id, cart_text(cart), cart_kb(cart)); return
    if data == "cart_clear":
        clear_cart(user_id)
        await edit_or_replace(query, context, chat_id, cart_text([]), cart_kb([])); return
    if data == "checkout":
        cart = get_cart(user_id)
        if not cart:
            await context.bot.send_message(chat_id, "Пусто!", reply_markup=main_menu_kb()); return
        set_state(user_id, "checkout", {})
        await context.bot.send_message(chat_id, "📝 <b>Оформление</b>\n\nНапишите <b>место встречи</b> и <b>время</b>.\nНапример: «м. Пушкинская, 18:00»", parse_mode="HTML"); return
    if data == "support":
        set_state(user_id, "support", {})
        await context.bot.send_message(chat_id, "📞 Опишите проблему:", parse_mode="HTML"); return
    if data == "replenish":
        set_state(user_id, "replenishment", {})
        await context.bot.send_message(chat_id, "📦 Какие товары хотите видеть?", parse_mode="HTML"); return

    # ===== АДМИН =====
    if data == "admin" and admin:
        await edit_or_replace(query, context, chat_id, admin_panel_text(), admin_kb()); return
    if data == "admin_add" and admin:
        await edit_or_replace(query, context, chat_id, "➕ Категория:", admin_add_cat_kb()); return
    if data.startswith("admin_addcat:") and admin:
        category = data.split(":",1)[1]
        set_state(user_id, "admin_add_name", {"category": category})
        await context.bot.send_message(chat_id, f"{CATEGORY_EMOJI[category]} Название:"); return
    if data == "admin_del" and admin:
        await edit_or_replace(query, context, chat_id, "🗑 Категория:", admin_del_cat_kb()); return
    if data.startswith("admin_delcat:") and admin:
        category = data.split(":",1)[1]
        products = get_products(category)
        if not products:
            await edit_or_replace(query, context, chat_id, f"{CATEGORY_EMOJI[category]} Пусто.", admin_del_cat_kb()); return
        await edit_or_replace(query, context, chat_id, f"🗑 <b>{CATEGORY_LABELS[category]}</b>", admin_del_prod_kb(category, products)); return
    if data.startswith("admin_delprod:") and admin:
        parts = data.split(":")
        category, pid = parts[1], parts[2]
        product = get_product(category, pid)
        if not product: return
        delete_product_db(category, pid)
        await query.answer(f"🗑 «{product['name']}» удалён")
        products = get_products(category)
        if not products:
            await edit_or_replace(query, context, chat_id, f"{CATEGORY_EMOJI[category]} Пусто.", admin_del_cat_kb())
        else:
            await edit_or_replace(query, context, chat_id, f"🗑 <b>{CATEGORY_LABELS[category]}</b>\n\n«{product['name']}» удалён.", admin_del_prod_kb(category, products))
        return

    # Заказы
    if data == "admin_orders" and admin:
        orders = get_all_orders()
        if not orders:
            await edit_or_replace(query, context, chat_id, "📋 Пусто.", admin_kb()); return
        await edit_or_replace(query, context, chat_id, "📋 <b>Все заказы</b>\n\nНажмите для деталей:", admin_orders_list_kb(orders)); return
    if data.startswith("admin_order_view:") and admin:
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order:
            await edit_or_replace(query, context, chat_id, "Не найден.", admin_kb()); return
        await edit_or_replace(query, context, chat_id, build_order_text(order), admin_order_detail_kb(order_id)); return

    # Админ подтверждает -> покупатель получает Да/Нет
    if data.startswith("admin_confirm:") and admin:
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order: return
        if order["status"] != "pending":
            await query.answer("Заказ уже обработан", show_alert=True); return
        update_order_status(order_id, "confirmed")
        try:
            await context.bot.send_message(order["user_id"],
                f"🔔 Ваш заказ #{order_id} подтверждён администратором!\n\nПолучили заказ?",
                reply_markup=deal_confirm_kb(order_id))
        except: pass
        order = get_order(order_id)
        await edit_or_replace(query, context, chat_id, build_order_text(order), admin_order_detail_kb(order_id)); return

    # Админ отменяет -> уведомление + удаление
    if data.startswith("admin_cancel:") and admin:
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order: return
        update_order_status(order_id, "cancelled")
        delete_order(order_id)
        try:
            await context.bot.send_message(order["user_id"], f"❌ Ваш заказ #{order_id} отменён администратором.")
        except: pass
        await edit_or_replace(query, context, chat_id, f"❌ Заказ #{order_id} отменён и удалён.", admin_kb()); return

    # Админ просто удаляет заказ
    if data.startswith("admin_delete_order:") and admin:
        order_id = data.split(":",1)[1]
        delete_order(order_id)
        await query.answer("🗑 Удалён")
        orders = get_all_orders()
        if not orders:
            await edit_or_replace(query, context, chat_id, "📋 Пусто.", admin_kb())
        else:
            await edit_or_replace(query, context, chat_id, "📋 <b>Все заказы</b>", admin_orders_list_kb(orders))
        return

    if data.startswith("admin_user_from_order:") and admin:
        order_id = data.split(":",1)[1]
        order = get_order(order_id)
        if not order: return
        await show_user_profile(update, context, chat_id, message_id, order["user_id"]); return
    if data.startswith("admin_user:") and admin:
        target_uid = int(data.split(":",1)[1])
        await show_user_profile(update, context, chat_id, message_id, target_uid); return
    if data.startswith("admin_msg:") and admin:
        target_uid = int(data.split(":",1)[1])
        set_state(user_id, f"admin_msg_user:{target_uid}", {})
        await context.bot.send_message(chat_id, f"💬 Сообщение для клиента (ID: {target_uid}):"); return
    if data == "admin_users" and admin:
        users = get_all_users()
        if not users:
            await edit_or_replace(query, context, chat_id, "👥 Пусто.", admin_kb()); return
        await edit_or_replace(query, context, chat_id, f"👥 <b>Клиенты</b> ({len(users)})", users_list_kb(users)); return

    # Запросы поставки
    if data == "admin_replenish" and admin:
        reqs = get_replenish_reqs()
        if not reqs:
            await edit_or_replace(query, context, chat_id, "📦 Пусто.", admin_kb()); return
        await edit_or_replace(query, context, chat_id, "📦 <b>Запросы поставки</b>\n\nНажмите для деталей:", replenish_list_kb(reqs)); return
    if data.startswith("admin_replenish_view:") and admin:
        req_id = data.split(":",1)[1]
        conn = get_db()
        row = conn.execute("SELECT * FROM replenish_reqs WHERE id=?", (req_id,)).fetchone()
        conn.close()
        if not row: return
        r = dict(row)
        text = f"📦 <b>Запрос поставки</b>\n\n👤 @{r['username']} (ID: {r['user_id']})\n📝 {r['text']}"
        await edit_or_replace(query, context, chat_id, text, replenish_detail_kb(req_id, r["user_id"])); return
    if data.startswith("admin_replenish_done:") and admin:
        parts = data.split(":")
        req_id, target_uid = parts[1], int(parts[2])
        req = delete_replenish_req(req_id)
        if req:
            try:
                await context.bot.send_message(target_uid, f"✅ Ваш запрос на поставку выполнен!\n\n📝 {req['text']}")
            except: pass
        await query.answer("✅ Отправлено")
        reqs = get_replenish_reqs()
        if not reqs:
            await edit_or_replace(query, context, chat_id, "📦 Пусто.", admin_kb())
        else:
            await edit_or_replace(query, context, chat_id, "📦 <b>Запросы поставки</b>", replenish_list_kb(reqs))
        return
    if data.startswith("admin_replenish_no:") and admin:
        parts = data.split(":")
        req_id, target_uid = parts[1], int(parts[2])
        req = delete_replenish_req(req_id)
        if req:
            try:
                await context.bot.send_message(target_uid, f"❌ К сожалению, запрошенный товар пока недоступен.\n\n📝 {req['text']}")
            except: pass
        await query.answer("✅ Отправлено")
        reqs = get_replenish_reqs()
        if not reqs:
            await edit_or_replace(query, context, chat_id, "📦 Пусто.", admin_kb())
        else:
            await edit_or_replace(query, context, chat_id, "📦 <b>Запросы поставки</b>", replenish_list_kb(reqs))
        return
    if data.startswith("admin_replenish_del:") and admin:
        req_id = data.split(":",1)[1]
        delete_replenish_req(req_id)
        await query.answer("🗑 Удалён")
        reqs = get_replenish_reqs()
        if not reqs:
            await edit_or_replace(query, context, chat_id, "📦 Пусто.", admin_kb())
        else:
            await edit_or_replace(query, context, chat_id, "📦 <b>Запросы поставки</b>", replenish_list_kb(reqs))
        return

    # Обращения поддержки
    if data == "admin_support" and admin:
        msgs = get_support_msgs()
        if not msgs:
            await edit_or_replace(query, context, chat_id, "📞 Пусто.", admin_kb()); return
        await edit_or_replace(query, context, chat_id, "📞 <b>Обращения поддержки</b>\n\nНажмите для деталей:", support_list_kb(msgs)); return
    if data.startswith("admin_support_view:") and admin:
        msg_id = data.split(":",1)[1]
        conn = get_db()
        row = conn.execute("SELECT * FROM support_msgs WHERE id=?", (msg_id,)).fetchone()
        conn.close()
        if not row: return
        m = dict(row)
        text = f"📞 <b>Обращение в поддержку</b>\n\n👤 @{m['username']} (ID: {m['user_id']})\n📝 {m['text']}"
        await edit_or_replace(query, context, chat_id, text, support_detail_kb(msg_id, m["user_id"])); return

    if data == "admin_broadcast" and admin:
        users = get_all_users()
        set_state(user_id, "admin_broadcast", {})
        await context.bot.send_message(chat_id, f"📢 Клиентов: {len(users)}\n\nТекст:", parse_mode="HTML"); return

    # Админы
    if data == "admin_admins" and admin:
        admins = get_admins()
        await edit_or_replace(query, context, chat_id, f"🔐 <b>Администраторы</b>\n\n👑 Главный админ: {MAIN_ADMIN_ID}\n👥 Добавленных: {len(admins)}\n\nНажмите чтобы удалить:", admin_list_kb(admins)); return
    if data == "admin_add_admin" and admin:
        set_state(user_id, "admin_add_admin_id", {})
        await context.bot.send_message(chat_id, "Введите Telegram ID нового админа:\n\n(Узнать ID: @userinfobot)"); return
    if data.startswith("admin_rm_admin:") and admin:
        rm_id = int(data.split(":",1)[1])
        if rm_id == MAIN_ADMIN_ID:
            await query.answer("Нельзя удалить главного админа!", show_alert=True); return
        remove_admin(rm_id)
        await query.answer("🗑 Админ удалён")
        admins = get_admins()
        await edit_or_replace(query, context, chat_id, f"🔐 <b>Администраторы</b>\n\n👑 Главный: {MAIN_ADMIN_ID}\n👥 Добавленных: {len(admins)}", admin_list_kb(admins)); return

    # Каналы подписки
    if data == "admin_channels" and admin:
        channels = get_sub_channels()
        await edit_or_replace(query, context, chat_id, f"📢 <b>Каналы подписки</b>\n\nВсего: {len(channels)}", sub_channels_kb(channels)); return
    if data == "admin_add_channel" and admin:
        set_state(user_id, "admin_add_channel", {})
        await context.bot.send_message(chat_id, "Добавление канала.\n\nФормат: <code>ID|ссылка</code>\nНапример: <code>-1001234567890|https://t.me/mychannel</code>", parse_mode="HTML"); return
    if data.startswith("admin_rm_channel:") and admin:
        ch_id = data.split(":",1)[1]
        remove_sub_channel(ch_id)
        await query.answer("🗑 Канал удалён")
        channels = get_sub_channels()
        await edit_or_replace(query, context, chat_id, f"📢 <b>Каналы подписки</b>\n\nВсего: {len(channels)}", sub_channels_kb(channels)); return

async def show_user_profile(update, context, chat_id, message_id, target_uid):
    user = get_user(target_uid)
    orders = get_orders_by_user(target_uid)
    reviews = get_reviews()
    user_reviews = [r for r in reviews if r["user_id"] == target_uid]
    replenish = get_replenish_reqs()
    user_reqs = [r for r in replenish if r["user_id"] == target_uid]
    name = f"@{user['username']}" if user and user["username"] else (user["first_name"] if user else "—")
    first_seen = user["first_seen"][:10] if user else "—"
    completed = [o for o in orders if o["status"] == "completed"]
    total_spent = sum(o["total_price"] for o in completed)
    text = f"👤 <b>Профиль</b>\n\n👤 {name}\n🆔 {target_uid}\n📅 {first_seen}\n\n📦 Заказов: {len(orders)}\n✅ Выполнено: {len(completed)}\n💰 Потрачено: {total_spent}₽\n⭐ Отзывов: {len(user_reviews)}\n📦 Запросов: {len(user_reqs)}\n"
    if orders:
        text += "\n<b>Заказы:</b>\n" + "\n".join(f"#{o['id']} — {o['total_price']}₽ — {o['status']}" for o in orders[:5])
    if user_reqs:
        text += "\n\n<b>Запросы:</b>\n" + "\n".join(f"📝 {r['text']}" for r in user_reqs[:3])
    await context.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=user_profile_kb(target_uid))

# ===== Запуск =====
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Бот запускается...")
    app.run_polling()

if __name__ == "__main__":
    main()
