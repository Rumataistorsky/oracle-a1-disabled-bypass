#!/usr/bin/env python3
"""60-metabase.py — створює в Metabase підключення до fleet, колекцію,
картки з deploy/cards.sql і дашборд.

Запускати на pve під root:
    python3 60-metabase.py /root/cards.sql

Потребує:
  /root/.metabase-api-key   — ключ з Admin → Settings → API keys (chmod 600)
  /root/fleet-credentials.txt — пароль fleet_ro

Нічого секретного не друкує. Ідемпотентний: повторний запуск не дублює
об'єкти, а доповнює відсутні.
"""
import json, os, re, sys, urllib.error, urllib.request

MB = "http://192.168.2.38:3000"
DB_HOST, DB_NAME, DB_USER = "192.168.2.25", "rotes_construction", "fleet_ro"
KEY_FILE = "/root/.metabase-api-key"
CRED_FILE = "/root/fleet-credentials.txt"

DISPLAY = {
    "kpi_year": "table", "benefit": "table", "monthly": "bar",
    "thresholds": "table", "cost_per_km": "line", "leads": "row",
    "reimbursements": "table", "data_quality": "table", "cra_logbook": "table",
}
TITLE = {
    "kpi_year": "Рік — підсумок",
    "benefit": "Taxable benefit (T4)",
    "monthly": "Км по місяцях",
    "thresholds": "Пороги CRA",
    "cost_per_km": "Вартість експлуатації",
    "leads": "Лійка лідів",
    "reimbursements": "Черга відшкодувань",
    "data_quality": "Якість даних",
    "cra_logbook": "Логбук у формі CRA",
}
ORDER = ["kpi_year", "thresholds", "benefit", "monthly", "cost_per_km",
         "leads", "reimbursements", "data_quality", "cra_logbook"]


def read_secret(path, pattern=None):
    if not os.path.exists(path):
        sys.exit(f"ПОМИЛКА: немає {path}")
    text = open(path).read()
    if pattern is None:
        return text.strip()
    m = re.search(pattern, text)
    if not m:
        sys.exit(f"ПОМИЛКА: не знайдено збіг у {path}")
    return m.group(1)


API_KEY = read_secret(KEY_FILE)
DB_PW = read_secret(CRED_FILE, r"user=fleet_ro password=(\S+)")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(MB + path, data=data, method=method,
                                 headers={"x-api-key": API_KEY,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"ПОМИЛКА {method} {path}: HTTP {e.code} {e.read().decode()[:300]}")


def parse_cards(path):
    text = open(path, encoding="utf-8").read()
    out, name, buf = [], None, []
    for line in text.splitlines():
        m = re.match(r"^--CARD:(\S+)\s*$", line)
        if m:
            if name:
                out.append((name, "\n".join(buf).strip()))
            name, buf = m.group(1), []
        elif name is not None:
            buf.append(line)
    if name:
        out.append((name, "\n".join(buf).strip()))
    return [(n, q) for n, q in out if q]


def main():
    cards_path = sys.argv[1] if len(sys.argv) > 1 else "/root/cards.sql"
    cards = parse_cards(cards_path)
    print(f"[0/4] знайдено карток у SQL: {len(cards)}")

    # 1. підключення до бази
    dbs = call("GET", "/api/database")
    dbs = dbs.get("data", dbs) if isinstance(dbs, dict) else dbs
    db = next((d for d in dbs if d["name"] == "ROTES Construction (fleet)"), None)
    if db:
        print(f"[1/4] база вже підключена, id={db['id']}")
    else:
        db = call("POST", "/api/database", {
            "name": "ROTES Construction (fleet)",
            "engine": "postgres",
            "details": {"host": DB_HOST, "port": 5432, "dbname": DB_NAME,
                        "user": DB_USER, "password": DB_PW,
                        "ssl": True, "ssl-mode": "require",
                        "ssl-use-client-auth": False,
                        "tunnel-enabled": False,
                        "schema-filters-type": "inclusion",
                        "schema-filters-patterns": "fleet"},
            "is_full_sync": True,
        })
        print(f"[1/4] базу підключено, id={db['id']}")
    db_id = db["id"]

    # 2. колекція
    cols = call("GET", "/api/collection")
    col = next((c for c in cols if c.get("name") == "Vehicle Logbook"), None)
    if not col:
        col = call("POST", "/api/collection",
                   {"name": "Vehicle Logbook",
                    "description": "Логбук корпоративного авто — звітність під CRA"})
        print(f"[2/4] колекцію створено, id={col['id']}")
    else:
        print(f"[2/4] колекція вже є, id={col['id']}")
    col_id = col["id"]

    # 3. картки
    existing = {c["name"]: c for c in call("GET", "/api/card")
                if c.get("collection_id") == col_id}
    card_ids = {}
    for name, query in cards:
        title = TITLE.get(name, name)
        if title in existing:
            card_ids[name] = existing[title]["id"]
            print(f"      картка вже є: {title}")
            continue
        c = call("POST", "/api/card", {
            "name": title,
            "dataset_query": {"type": "native", "database": db_id,
                              "native": {"query": query, "template-tags": {}}},
            "display": DISPLAY.get(name, "table"),
            "visualization_settings": {},
            "collection_id": col_id,
        })
        card_ids[name] = c["id"]
        print(f"      + {title}")
    print(f"[3/4] карток готово: {len(card_ids)}")

    # 4. дашборд
    dashes = call("GET", "/api/dashboard")
    dash = next((d for d in dashes if d.get("name") == "Vehicle Logbook"), None)
    if not dash:
        dash = call("POST", "/api/dashboard",
                    {"name": "Vehicle Logbook", "collection_id": col_id})
        print(f"[4/4] дашборд створено, id={dash['id']}")
    else:
        print(f"[4/4] дашборд уже є, id={dash['id']}")

    full = call("GET", f"/api/dashboard/{dash['id']}")
    if full.get("dashcards"):
        print("      картки вже розкладені — розкладку не чіпаю")
    else:
        dashcards, row = [], 0
        for i, name in enumerate(ORDER):
            if name not in card_ids:
                continue
            wide = name in ("monthly", "cost_per_km", "cra_logbook", "reimbursements")
            w, h = (24, 8) if wide else (12, 5)
            col_pos = 0 if wide else (0 if i % 2 == 0 else 12)
            dashcards.append({"id": -(i + 1), "card_id": card_ids[name],
                              "row": row, "col": col_pos, "size_x": w, "size_y": h,
                              "parameter_mappings": [], "visualization_settings": {}})
            if wide or col_pos == 12:
                row += h
        call("PUT", f"/api/dashboard/{dash['id']}", {"dashcards": dashcards})
        print(f"      розкладено карток: {len(dashcards)}")

    print(f"ГОТОВО — https://metabase.rotes.ca/dashboard/{dash['id']}")


if __name__ == "__main__":
    main()
