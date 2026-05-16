"""
Nanoboost — Test Data Seed Script
Manager test qilishi uchun: users + games + services + options yaratadi.
Postgres orders + clients alohida SQL skript orqali.

Run: python scripts/seed_test_data.py
"""

import json
import sys
import urllib.request
import urllib.error

API = "http://localhost:8000/api/v1"
SUPERADMIN = {"email": "admin@nanoboost.io", "password": "ChangeMeImmediately123!"}


def request(method, url, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {msg}") from e


def safe(label, fn):
    try:
        result = fn()
        print(f"  OK    {label}")
        return result
    except RuntimeError as e:
        if "409" in str(e) or "already exists" in str(e):
            print(f"  SKIP  {label} (allaqachon mavjud)")
            return None
        print(f"  FAIL  {label}: {e}")
        return None


def main():
    print("=" * 60)
    print("NANOBOOST — TEST DATA SEED")
    print("=" * 60)

    print("\n[1/4] Superadmin login...")
    login = request("POST", f"{API}/auth/login", SUPERADMIN)
    token = login["access_token"]
    print(f"  OK    superadmin: {login['user']['email']}")

    print("\n[2/4] Test users yaratish...")
    users = [
        {
            "email": "admin2@nanoboost.io",
            "password": "Admin123!",
            "role": "admin",
            "full_name": "Test Admin",
        },
        {
            "email": "manager@nanoboost.io",
            "password": "Manager123!",
            "role": "manager",
            "full_name": "Test Manager",
        },
        {
            "email": "viewer@nanoboost.io",
            "password": "Viewer123!",
            "role": "viewer",
            "full_name": "Test Viewer",
        },
    ]
    for u in users:
        safe(
            f"user {u['email']:<30} ({u['role']})",
            lambda u=u: request("POST", f"{API}/users", u, token),
        )

    print("\n[3/4] Games yaratish...")
    games_data = [
        {
            "slug": "gta5",
            "name": "GTA 5 Online",
            "description": "Grand Theft Auto V Online — boosting xizmatlari",
            "sort_order": 0,
            "status": "active",
        },
        {
            "slug": "wow",
            "name": "World of Warcraft",
            "description": "WoW boosting (kelajak)",
            "sort_order": 1,
            "status": "coming_soon",
        },
        {
            "slug": "destiny2",
            "name": "Destiny 2",
            "description": "Destiny 2 (yopiq)",
            "sort_order": 2,
            "status": "hidden",
        },
    ]
    games_by_slug = {}
    for g in games_data:
        result = safe(
            f"game {g['slug']:<10} ({g['status']})",
            lambda g=g: request("POST", f"{API}/games", g, token),
        )
        if result:
            games_by_slug[g["slug"]] = result["id"]

    if "gta5" not in games_by_slug:
        existing = request("GET", f"{API}/games?page_size=100", token=token)
        for g in existing.get("items", []):
            games_by_slug[g["slug"]] = g["id"]

    gta5_id = games_by_slug.get("gta5")
    if not gta5_id:
        print("\n  FATAL: gta5 game topilmadi, services yaratib bo'lmaydi")
        sys.exit(1)

    print("\n[4/4] Services yaratish (GTA 5 uchun)...")
    services_data = [
        {
            "game_id": gta5_id,
            "slug": "gta-cash-cars-ps",
            "title": "GTA Online Cash + Cars Boost PS4/PS5",
            "platform": "ps",
            "image_alt": "GTA Cash + Cars Boost PS",
            "description": [
                "Upgrade your GTA Online account on PS4/PS5.",
                "Cash + premium cars in one package.",
            ],
            "what_you_get": [
                {
                    "title": "GTA Online Money",
                    "lead": "Your account receives:",
                    "items": ["Cash balance", "Properties access", "Vehicle upgrades"],
                },
                {
                    "title": "Premium Cars",
                    "lead": "Setup includes:",
                    "items": [
                        "High-performance vehicles",
                        "Fully upgraded engine",
                        "Custom configuration",
                    ],
                },
            ],
            "sections": [
                {
                    "title": "Designed for PlayStation",
                    "texts": ["Optimized specifically for PS4/PS5 accounts."],
                },
                {
                    "title": "Service Format",
                    "texts": ["After checkout, the upgrade process begins."],
                },
            ],
            "seo_title": "GTA Online Cash & Cars Boost PS4/PS5",
            "seo_description": "Buy GTA Online cash and cars for PS4 & PS5.",
            "is_featured": True,
            "is_active": True,
            "sort_order": 0,
            "options": [
                {
                    "label": "20 million",
                    "price_usd": 15.99,
                    "price_eur": 13.99,
                    "is_default": True,
                    "sort_order": 0,
                },
                {
                    "label": "50 million",
                    "price_usd": 29.99,
                    "price_eur": 25.99,
                    "is_default": False,
                    "sort_order": 1,
                },
                {
                    "label": "100 million",
                    "price_usd": 44.99,
                    "price_eur": 38.99,
                    "is_default": False,
                    "sort_order": 2,
                },
                {
                    "label": "1 Billion",
                    "price_usd": 179.99,
                    "price_eur": 153.99,
                    "is_default": False,
                    "sort_order": 3,
                },
            ],
        },
        {
            "game_id": gta5_id,
            "slug": "gta-cash-ps",
            "title": "GTA Online Cash Boost PS4/PS5",
            "platform": "ps",
            "description": ["Increase your in-game balance quickly.", "Skip repetitive grinding."],
            "what_you_get": [
                {
                    "title": "Money Upgrade",
                    "lead": "Your account receives:",
                    "items": ["Cash balance increase", "Faster progress"],
                },
            ],
            "sections": [
                {"title": "Optimized for PS", "texts": ["Designed for PS4/PS5 accounts."]},
            ],
            "is_active": True,
            "is_featured": False,
            "sort_order": 1,
            "options": [
                {
                    "label": "20 million",
                    "price_usd": 19.99,
                    "price_eur": 16.99,
                    "is_default": True,
                    "sort_order": 0,
                },
                {
                    "label": "30 million",
                    "price_usd": 29.99,
                    "price_eur": 25.99,
                    "is_default": False,
                    "sort_order": 1,
                },
            ],
        },
        {
            "game_id": gta5_id,
            "slug": "gta-level-ps",
            "title": "GTA Online Level Boost PS4/PS5",
            "platform": "ps",
            "description": ["Reach higher ranks faster.", "Access advanced equipment."],
            "what_you_get": [
                {
                    "title": "Rank Progression",
                    "lead": "Your account unlocks:",
                    "items": ["Advanced weapons", "New missions", "Higher reputation"],
                },
            ],
            "sections": [
                {"title": "Built for PS", "texts": ["Optimized for PS4/PS5."]},
            ],
            "is_active": True,
            "is_featured": False,
            "sort_order": 2,
            "options": [
                {
                    "label": "50 level",
                    "price_usd": 29.99,
                    "price_eur": 25.99,
                    "is_default": True,
                    "sort_order": 0,
                },
                {
                    "label": "100 level",
                    "price_usd": 49.99,
                    "price_eur": 42.99,
                    "is_default": False,
                    "sort_order": 1,
                },
                {
                    "label": "200 level",
                    "price_usd": 79.99,
                    "price_eur": 68.99,
                    "is_default": False,
                    "sort_order": 2,
                },
            ],
        },
        {
            "game_id": gta5_id,
            "slug": "gta-modded-xbox",
            "title": "GTA Online Modded Account Xbox One/Series",
            "platform": "xbox",
            "description": ["Start GTA Online with a powerful setup."],
            "what_you_get": [
                {
                    "title": "Modded Account",
                    "lead": "Includes:",
                    "items": ["High money balance", "High level", "Premium vehicles"],
                },
            ],
            "sections": [
                {"title": "Xbox Compatibility", "texts": ["Prepared for Xbox One/Series."]},
            ],
            "is_active": True,
            "is_featured": True,
            "sort_order": 0,
            "options": [
                {
                    "label": "level 100 + 15 million",
                    "price_usd": 29.99,
                    "price_eur": 25.99,
                    "is_default": True,
                    "sort_order": 0,
                },
                {
                    "label": "level 120 + 1 Billion",
                    "price_usd": 199.99,
                    "price_eur": 170.99,
                    "is_default": False,
                    "sort_order": 1,
                },
            ],
        },
        {
            "game_id": gta5_id,
            "slug": "gta-unlock-pc",
            "title": "GTA Online Unlock All PC",
            "platform": "pc",
            "description": ["Unlock the full potential of your GTA Online account."],
            "what_you_get": [
                {
                    "title": "Full Account Upgrade",
                    "lead": "Your account receives:",
                    "items": ["Maximum stats", "All weapons unlocked", "Achievements unlocked"],
                },
            ],
            "sections": [
                {"title": "PC Optimized", "texts": ["Designed for GTA Online PC."]},
            ],
            "is_active": True,
            "is_featured": True,
            "sort_order": 0,
            "options": [
                {
                    "label": "Unlock All",
                    "price_usd": 29.99,
                    "price_eur": 25.99,
                    "is_default": True,
                    "sort_order": 0,
                },
            ],
        },
    ]
    for s in services_data:
        safe(
            f"service {s['slug']:<25} ({s['platform']:<4})",
            lambda s=s: request("POST", f"{API}/services", s, token),
        )

    print("\n" + "=" * 60)
    print("SEED YAKUNLANDI")
    print("=" * 60)
    print("\nTest user'lar:")
    print("  superadmin@: admin@nanoboost.io   / ChangeMeImmediately123!")
    print("  admin     :  admin2@nanoboost.io  / Admin123!")
    print("  manager   :  manager@nanoboost.io / Manager123!")
    print("  viewer    :  viewer@nanoboost.io  / Viewer123!")
    print("\nKeyin: orders + clients uchun seed_orders.sql ishga tushiring")


if __name__ == "__main__":
    main()
