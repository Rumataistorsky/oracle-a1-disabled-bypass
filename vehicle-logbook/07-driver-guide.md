# 07 — Памʼятка водія

Роздрукувати, покласти в бардачок. Одна сторінка.

---

## 🇺🇦 Українською

### Що від тебе потрібно

Чотири речі. Все інше система робить сама.

**1. Ввечері — розібрати поїздки.**
Бот надішле картки за день. По кожній тисни кнопку:

* **Оцінка/замір** — їздив дивитись роботу, яку ще не робимо
* **Обʼєкт у роботі** — їздив на активний обʼєкт
* **Зустріч** — із замовником чи субпідрядником. Байдуже де: кафе,
  парковка, чужий офіс. Місце не має значення, важлива причина
* **Постачальник** — магазин, склад, матеріали
* **Інше по роботі** — банк, пошта, сервіс, будь-що робоче, що не підійшло вище
* **Особисте** — будь-яка поїздка не по роботі

Усе, крім «Постачальник» і «Особисте», бот перепитає одним рядком.
Питання залежить від кнопки: після зустрічі — **«з ким і про що»**,
після обʼєкта — **«який обʼєкт і що робили»**.
Пиши конкретно: **«замір — заміна покрівлі»**, а не «робота».
Це поле читає податкова.

Під полем вводу є три кнопки — **📋 Поїздки**, **📟 Одометр**, **📊 Статус**.
Якщо їх не видно, напиши `меню`.

**📋 Поїздки** — бот пришле список того, що ще не закрите, з номерами. Закрити будь-яку можна одним рядком:

```
15 замір даху
```

Номер із списку, пробіл, і що там робив. Картку шукати не треба.

**2. Раз на місяць — число з одометра.**
Просто набери його в чат: `47385`. Нічого більше.
Бот одразу відповість, наскільки GPS недобрав пробіг.
Трекер завжди бачить менше за одометр — саме ці незакриті кілометри
податкова рахує як особисті.

Фото панелі — бонус, але надсилай його **файлом**, не фото:
Telegram стискає фото і зрізає час зйомки, а саме час і є доказом.

**3. Кожна заправка — два фото.**
Чек і одометр. Скидаєш у чат боту.
**Навіть якщо платив своїми грошима або готівкою.**
Без чека компанія не може ні відшкодувати тобі, ні списати витрату.

**4. На обʼєкті, куди їдеш вперше — одне фото будівлі.**
Десять секунд. Це доказ, що ми там були. Особливо важливо, коли не знаємо
навіть імені господаря — тільки адресу.

### Чого робити не треба

* Не записувати кілометри вручну — рахує трекер
* Не вводити адреси — підставляються самі
* Не переживати, якщо забув відповісти одразу: картки висять добу

### Важливе

* **Поїздка дім → обʼєкт — це робота.** Наша база і є офіс компанії.
* **Не бійся тиснути «Особисте».** Це нормально і так має бути.
  Логбук, де все 100% робота, викликає більше питань, ніж кілька особистих поїздок.
* Якщо бот мовчить два дні — скажи. Значить трекер відвалився.

### Питання

Пиши в той самий чат, де приходять картки.

---

## 🇬🇧 English

### What we need from you

Four things. The system handles the rest.

**1. In the evening — sort your trips.**
The bot sends you cards for the day. Tap one button per trip:

* **Estimate / site visit** — went to look at work we haven't started
* **Active job site** — went to a job we're working on
* **Meeting** — with a client or a contractor. Anywhere: a café, a parking
  lot, someone else's office. The place doesn't matter, the reason does
* **Supplier** — store, yard, materials
* **Other work trip** — bank, post office, service shop, anything else on the job
* **Personal** — anything not work

Everything except *Supplier* and *Personal* gets one follow-up line.
The question depends on the button: after a meeting — **who with and what about**,
after a job site — **which site and what you did**.
Be specific: **"estimate — roof replacement"**, not "work".
The tax authority reads this field.

There are three buttons under the input field — **📋 Поїздки** (trips),
**📟 Одометр** (odometer), **📊 Статус**. If you don't see them, type `меню`.

**📋 Поїздки** sends a numbered list of everything still open. Close any of them with one line:

```
15 roof measurement
```

Number from the list, a space, and what you did there. No need to find the card.

**2. Once a month — the odometer number.**
Just type it into the chat: `47385`. Nothing else.
The bot replies with how much mileage GPS missed.
The tracker always sees less than the odometer, and those unaccounted
kilometres are what the tax authority counts as personal.

A photo of the cluster helps too, but send it **as a file**, not as a photo:
Telegram compresses photos and strips the capture time, and the time is the proof.

**3. Every fill-up — two photos.**
Receipt and odometer. Send both to the bot.
**Even if you paid with your own card or cash.**
Without a receipt the company can neither reimburse you nor deduct the expense.

**4. First visit to a site — one photo of the building.**
Ten seconds. It proves we were there. This matters most when we only have
an address and no owner name.

### What you don't need to do

* Don't write down kilometres — the tracker counts them
* Don't type addresses — they fill in automatically
* Don't worry if you miss a card right away — they stay open for 24 hours

### Important

* **Home → job site is business.** Our base is the company office.
* **Don't be afraid to tap "Personal".** It is normal and expected.
  A logbook showing 100% business raises more questions than a few personal trips.
* If the bot goes quiet for two days — tell us. The tracker has dropped off.

### Questions

Same chat where the cards arrive.
