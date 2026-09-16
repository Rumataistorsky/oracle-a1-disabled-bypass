# 06 — Звітність (Metabase, LXC 509)

Metabase підключається до `rotes-db` (LXC 415), схема `fleet`.
Уся важка логіка вже у в'юхах із `04-data-model.sql`.

## Дашборд «Vehicle Logbook»

### Верхній ряд — показники року

```sql
SELECT business_pct, business_km, personal_km, unclassified_km, total_km
FROM fleet.v_annual_summary
WHERE tax_year = EXTRACT(YEAR FROM current_date)::int;
```

Пороги, які треба тримати на очах постійно:

| Показник | Ціль | Чому |
|---|---|---|
| `business_pct` | **≥ 50%** | нижче — зникає право на знижений standby і на HST ITC |
| `personal_km` | **≤ 20 004** | вище — знижений standby недоступний |
| `unclassified_km` | **0** | некласифіковані при аудиті трактуються не на твою користь |

### Розрахунок benefit

```sql
SELECT label, tax_year, business_pct, personal_km,
       standby_full, reduction_eligible, standby_applicable,
       operating_benefit, total_benefit
FROM fleet.v_taxable_benefit
WHERE tax_year = EXTRACT(YEAR FROM current_date)::int;
```

Це число йде бухгалтеру на T4. Поруч показувати `standby_full` — щоб було
видно, скільки логбук зекономив.

### Динаміка по місяцях

```sql
SELECT date_trunc('month', trip_date)::date AS month,
       SUM(distance_km) FILTER (WHERE classification = 'business')  AS business,
       SUM(distance_km) FILTER (WHERE classification IN ('personal','commute')) AS personal,
       ROUND(100.0 * SUM(distance_km) FILTER (WHERE classification = 'business')
             / NULLIF(SUM(distance_km), 0), 1) AS pct
FROM fleet.trips
WHERE trip_date >= date_trunc('year', current_date)
GROUP BY 1 ORDER BY 1;
```

### Вартість експлуатації

```sql
WITH km AS (
    SELECT date_trunc('month', trip_date)::date AS month, SUM(distance_km) AS km
    FROM fleet.trips GROUP BY 1
), fuel AS (
    SELECT date_trunc('month', occurred_on)::date AS month,
           SUM(total_amount) AS spend, SUM(litres) AS litres
    FROM fleet.fuel_events GROUP BY 1
)
SELECT k.month, k.km, f.spend, f.litres,
       ROUND(f.spend / NULLIF(k.km, 0), 3)           AS cost_per_km,
       ROUND(100 * f.litres / NULLIF(k.km, 0), 2)    AS l_per_100km
FROM km k LEFT JOIN fuel f USING (month)
ORDER BY k.month;
```

`l_per_100km` — не бухгалтерія, а контроль. Паспортна витрата Pacifica V6
відома; стабільне відхилення вгору означає або стиль їзди, або зливання пального.

### Лійка лідів

```sql
SELECT outcome, COUNT(*) AS leads,
       ROUND(SUM(t.km)::numeric, 0) AS km_spent
FROM fleet.leads l
LEFT JOIN LATERAL (
    SELECT SUM(distance_km) AS km FROM fleet.trips WHERE lead_id = l.id
) t ON true
GROUP BY outcome ORDER BY leads DESC;
```

Побічний, але корисний продукт: скільки кілометрів коштує один виграний
контракт і який відсоток виїздів на оцінку конвертується.

### Черга відшкодувань

```sql
SELECT * FROM fleet.v_reimbursement_queue;
```

З 20 січня має бути порожня — інакше спливає 45-денний дедлайн.

---

## Річний експорт для бухгалтера

Воркфлоу n8n, раз на місяць 1 числа + фінальний прогін у січні.

### 1. Логбук у формі CRA

```sql
SELECT * FROM fleet.v_cra_logbook
WHERE "Date" BETWEEN :from AND :to;
```

Експорт у CSV **і** PDF. PDF — тому що редагований файл при аудиті важить менше,
ніж зафіксований документ.

### 2. Титульна сторінка звіту

Має містити:

* авто: марка, модель, рік, VIN;
* одометр на 1 січня і 31 грудня + посилання на фото;
* total km / business km / personal km / business %;
* заяву, що домашня адреса є principal place of business компанії;
* перелік особистих авто власника (з `08-vehicle-policy.md`) — це пояснює,
  чому особистий пробіг корпоративного авто низький.

### 3. Аркуш розрахунку benefit

```sql
SELECT * FROM fleet.v_taxable_benefit WHERE tax_year = :year;
```

### 4. Аркуш витрат

```sql
SELECT occurred_on, 'fuel' AS kind, vendor, total_amount, hst_amount, paid_by,
       receipt_url IS NOT NULL AS has_receipt
FROM fleet.fuel_events WHERE EXTRACT(YEAR FROM occurred_on) = :year
UNION ALL
SELECT occurred_on, category, vendor, total_amount, hst_amount, paid_by,
       receipt_url IS NOT NULL
FROM fleet.other_costs WHERE EXTRACT(YEAR FROM occurred_on) = :year
ORDER BY 1;
```

### 5. Складання

Файли лягають у Nextcloud (LXC 416):

```
/Accounting/Vehicle-Log/{рік}/
    logbook-{рік}.pdf
    logbook-{рік}.csv
    benefit-calculation-{рік}.pdf
    expenses-{рік}.csv
    odometer-year-start.jpg
    odometer-year-end.jpg
    vehicle-use-policy-signed.pdf
```

Папка розшарена бухгалтеру через `nc_share_create`. Retention — 7 років,
base year окремо позначити, бо його треба тримати 6 років після останнього
використання як базового.

---

## Контроль якості даних

Окремий блок дашборда. Якщо тут не нулі — звітність нечесна.

```sql
-- поїздки без мети
SELECT COUNT(*) FROM fleet.trips
WHERE classification = 'business' AND (purpose IS NULL OR btrim(purpose) = '');

-- бізнес-поїздки без жодного доказу
SELECT COUNT(*) FROM fleet.trips
WHERE classification = 'business' AND lead_id IS NULL
  AND invoice_ninja_client_id IS NULL AND evidence_photo_count = 0;

-- класифіковані дефолтом, не людиною
SELECT COUNT(*), SUM(distance_km) FROM fleet.trips
WHERE classified_by = 'default';

-- позначені на перегляд і досі не переглянуті
SELECT COUNT(*) FROM fleet.trips
WHERE review_flag AND classified_by IN ('default', 'rule');
```
