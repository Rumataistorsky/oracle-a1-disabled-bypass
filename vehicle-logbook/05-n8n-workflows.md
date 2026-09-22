# 05 — Воркфлоу n8n (LXC 411)

Пʼять воркфлоу. Усі пишуть у схему `fleet` на LXC 415.

| # | Назва | Розклад | Призначення |
|---|---|---|---|
| 1 | `fleet-sync-trips` | щогодини | забрати поїздки з Traccar, попередньо класифікувати |
| 2 | `fleet-classify-bot` | подія | питати водія по некласифікованих, приймати відповідь |
| 3 | `fleet-sync-geofences` | щодня | адреси клієнтів Invoice Ninja → geofences Traccar |
| 4 | `fleet-fuel-receipt` | подія | фото чека → OCR → expense в Invoice Ninja |
| 5 | `fleet-watchdog` | кожні 6 год | алерти: пристрій мовчить, чек відсутній, місяць не закритий |

---

## 1. `fleet-sync-trips`

```
Cron (7 * * * *)
  → HTTP GET  Traccar /api/reports/route?deviceId=&from=&to=   ← сирі позиції
  → HTTP GET  Traccar /api/reports/trips?deviceId=&from=&to=
  → Function  нормалізація + правила класифікації + пошук провалів звʼязку
  → Postgres  INSERT ... ON CONFLICT (traccar_trip_key) DO UPDATE
```

Traccar: авторизація Basic або токен. Вікно запиту — останні 48 год
із перекриттям, ідемпотентність забезпечує `traccar_trip_key`.

### Правила попередньої класифікації

Виконуються по порядку, перше спрацювання виграє:

```js
// 1. Старт із HOME-OFFICE і фініш у відомого клієнта/постачальника → бізнес
if (startGeofence === 'HOME-OFFICE' && /^(CLIENT|SUPPLIER)-/.test(endGeofence))
    return { classification: 'business', classified_by: 'geofence' };

// 2. Фініш у HOME-OFFICE із відомого клієнта/постачальника → бізнес (повернення)
if (/^(CLIENT|SUPPLIER)-/.test(startGeofence) && endGeofence === 'HOME-OFFICE')
    return { classification: 'business', classified_by: 'geofence' };

// 3. Будь-який кінець у PERSONAL-* → особисте
if (/^PERSONAL-/.test(startGeofence) || /^PERSONAL-/.test(endGeofence))
    return { classification: 'personal', classified_by: 'geofence' };

// 4. Дім водія ↔ база, коли дім водія не є офісом → commute
if (driver.home_is_office === false && isHomeBasePair(startGeofence, endGeofence))
    return { classification: 'commute', classified_by: 'rule' };

// 5. Решта — питаємо водія
return { classification: 'unclassified', classified_by: null };
```

### Прапорець «схоже на особисте»

Не змінює класифікацію, лише підсвічує в боті й у звіті:

```js
const d = new Date(startedAt);
const weekend = d.getDay() === 0 || d.getDay() === 6;
const late    = d.getHours() >= 19 || d.getHours() < 6;
const unknown = !startGeofence && !endGeofence;

if (weekend || late || unknown) {
    review_flag   = true;
    review_reason = [weekend && 'вихідний', late && 'позаробочий час',
                     unknown && 'обидві точки поза geofence']
                    .filter(Boolean).join(', ');
}
```

### Провал звʼязку всередині поїздки

Телефон із агресивним енергозбереженням замовкає на 10–30 хвилин посеред
рейсу. Traccar не повідомляє про це нічим: він просто зшиває дірку прямою
лінією і віддає **одну** поїздку замість двох, із заниженою відстанню.
Заїзд, де водій узяв чек, у логбуку не існує взагалі.

Звіт `trips` таку дірку не показує, тому воркфлоу тягне ще й `route` —
сирі позиції за те саме вікно — і міряє найбільшу паузу між сусідніми
точками всередині кожної поїздки:

```js
const gap = worstGap(t.startTime, t.endTime);   // { min, m }
const stitched = gap.min >= 5 && gap.m >= 300;  // пауза + зміщення
```

Пауза без зміщення — просто стоянка, її не чіпаємо. Пауза зі стрибком
на сотні метрів іде в `review_reason` відкритим текстом:

```
провал звʼязку 27 хв, стрибок 5.0 км по прямій —
відстань занижена, можливо це дві поїздки
```

На живих даних 22.09 детектор сам знайшов обидва випадки, які до того
знаходились руками: 13 хв / 1.0 км і 27 хв / 5.0 км.

> Це компенсація, а не лікування. Лікування — апаратний трекер
> (Teltonika FMM003), якому нема чого «засинати».

> Мета правил — не «максимізувати бізнес-відсоток», а щоб число витримало
> перевірку. Логбук зі 100% бізнесу — червоний прапор, а не перемога.

---

## 2. `fleet-classify-bot`

Бот живе на LXC 422 (bots-hub), канал — Telegram або SimpleX.

```
Postgres  SELECT * FROM fleet.trips WHERE classification='unclassified'
  → Loop
      → Bot  надіслати картку поїздки з кнопками
  ← Webhook  відповідь водія
      → Postgres  UPDATE trips SET classification, purpose, lead_id
      → Switch    якщо «Оцінка» → гілка створення ліда
```

### Картка поїздки

```
🚐 16.09, 14:20 → 15:05 · 34 км
Home office → 47 Maple Dr, Dartmouth
⚠️ обидві точки поза geofence

[ Оцінка/замір ]    [ Обʼєкт у роботі ]
[ Зустріч ]         [ Постачальник ]
[ Інше по роботі ]  [ Особисте ]
```

Набір кнопок покриває весь робочий день, а не лише обʼєкти. «Зустріч» і
«Інше по роботі» додані тому, що половина робочих поїздок закінчується не
на обʼєкті: кафе, парковка, чужий офіс, банк. Без своєї кнопки така поїздка
лишалася без типу назавжди — і жодна інша кнопка її не описувала чесно.

Після вибору бот питає один рядок, і питання залежить від кнопки:
після «Зустріч» — «з ким і про що», після «Обʼєкт у роботі» — «який обʼєкт
і що робили». Текст іде в `trips.purpose`. Це і є поле «мета» для CRA,
тому формулювання має бути конкретним: `замір — заміна покрівлі`,
а не `робота`.

«Постачальник» мету не питає — він її й записує (`закупівля у постачальника`).
Інакше поїздка діставала тип, лишалася без мети, і закрити цю прогалину було
нічим: картка вже надіслана, друга не прийде.

Кнопки на вже надісланій картці Telegram сам не оновлює. Після зміни набору
кнопок треба вручну запустити `Fleet — Refresh Card Keyboards (logbook)` —
він перемальовує клавіатури на місці, не сиплячи в чат дублі карток.

### Гілка створення ліда

```
Function   геокодувати фініш (адреса вже є з Traccar)
  → Postgres   INSERT INTO fleet.leads (address, lat, lon, what_quoted)
  → HTTP POST  Invoice Ninja /api/v1/clients
               name = "Lead — {address}"
  → HTTP POST  Invoice Ninja /api/v1/quotes   (чернетка, не надсилати)
  → HTTP       Immich: створити/знайти альбом "Site Visits {рік}",
               призначити фото за GPS+датою
  → Postgres   UPDATE leads SET invoice_ninja_client_id, quote_id, album_id
  → Postgres   UPDATE trips SET lead_id
```

Invoice Ninja v5: заголовок `X-API-TOKEN`, база `/api/v1`.

**Навіщо lead навіть без імені клієнта:** це корпоративний артефакт, який
назавжди привʼязує поїздку до бізнес-мети. Разом із гео-фото це закриває
питання «доведіть, що ви туди їздили по роботі».

### Дефолт при мовчанні

Немає відповіді 24 години → `classification = 'personal'`,
`classified_by = 'default'`. Консервативно і безпечно: завищений особистий
пробіг коштує грошей, занижений коштує донарахувань.

Бот раз на тиждень шле зведення: скільки поїздок пішло в дефолт —
щоб їх можна було переглянути, поки памʼять свіжа.

---

## 3. `fleet-sync-geofences`

```
Cron (0 4 * * *)
  → HTTP GET   Invoice Ninja /api/v1/clients?include=  (адреси)
  → HTTP GET   Invoice Ninja /api/v1/projects
  → Function   геокодувати нові адреси
  → HTTP GET   Traccar /api/geofences         (що вже є)
  → Function   diff
  → HTTP POST  Traccar /api/geofences         (CLIENT-{id}, коло 150 м)
```

Нові клієнти підхоплюються автоматично, вручну geofences не заводити.
`SUPPLIER-*` і `PERSONAL-*` ведуться руками — їх одиниці.

---

## 4. `fleet-fuel-receipt`

```
Trigger  файл у Nextcloud /Fleet/Receipts/inbox/
  → HTTP POST  Docling (LXC 620) :5001  → OCR
  → Function   парсинг: дата, сума, HST, літри, вендор
  → Bot        підтвердити розпізнане + запитати «хто платив?»
                 [ Корпоративна ]  [ Особиста ]  [ Готівка ]
  ← Webhook    відповідь
  → Postgres   INSERT INTO fleet.fuel_events
  → HTTP POST  Invoice Ninja /api/v1/expenses
                 category = Fuel, vendor = АЗС
                 custom_value1 = paid_by
  → IF paid_by <> 'corporate_card'
       → Postgres  reimbursement_status = 'pending'
  → Nextcloud  перемістити файл у /Fleet/Receipts/{рік}/{місяць}/
```

Чек обовʼязковий незалежно від того, хто платив: без нього немає ні
вирахування, ні HST ITC, ні зменшення operating benefit.

---

## 5. `fleet-watchdog`

```
Cron (0 */6 * * *)
```

| Перевірка | Умова | Дія |
|---|---|---|
| Пристрій мовчить | остання позиція старша за 36 год | алерт у SimpleX + Telegram |
| Заправка без чека | приріст одометра > 500 км без `fuel_events` | нагадування в бота |
| Некласифіковані | є записи старші за 72 год | зведення власнику |
| Розрив одометра | \|GPS-пробіг − одометр\| > 3% за місяць | алерт на звірку |
| Місяць не закритий | 5 число, попередній місяць без експорту | нагадування |
| Дедлайн відшкодування | 20 січня, є `pending` за попередній рік | алерт: залишилось 25 днів із 45 |
| Одометр на кінець року | 28 грудня, немає `year_end` | нагадування зробити фото |

Алерт «пристрій мовчить» — найважливіший у списку. Саме тиха втрата даних
руйнує base year, а не разові помилки класифікації.

---

## Облікові дані

Токени Traccar, Invoice Ninja, Immich, Nextcloud, бота — у Vaultwarden (VM 103),
у n8n підключаються як Credentials. У git не потрапляє нічого.
