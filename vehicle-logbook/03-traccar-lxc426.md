# 03 — Traccar (LXC 426) — РОЗГОРНУТО

Стан на **2026-09-16**. Розділ описує фактично розгорнуту систему, а не план.
Автоматизація — у `deploy/`.

## Фактичні параметри

| | |
|---|---|
| Контейнер | LXC **426** `traccar`, Debian 13, unprivileged |
| IP | **192.168.2.66**/24, gw 192.168.2.240, DNS 192.168.2.241 |
| Ресурси | 2 vCPU / 2 GB RAM / 512 MB swap / 16 GB на пулі `VM` |
| Traccar | **6.15.3** (власний JRE Adoptium 25, системна Java не потрібна) |
| Веб | `https://fleet.rotes.ca` через Caddy (LXC 514, 192.168.2.48) |
| Порт пристрою | **5027** (`teltonika`) |
| onboot | так, перевірено перезавантаженням |

> `.56` з чернетки плану виявився зайнятим — блок `192.168.2.12–.65` щільно
> заповнений. Перед будь-яким новим контейнером звіряти `ip neigh` і
> `grep -oE 'ip=192\.168\.2\.[0-9]+' /etc/pve/lxc/*.conf`.

## Розкладка баз даних

PostgreSQL 17 на LXC **415** (`rotes-db`, **192.168.2.25** — не `.15`).

| База | Схема | Призначення | Користувач |
|---|---|---|---|
| `traccar` | `public` | таблиці самого Traccar (51 шт., Liquibase) | `traccar` |
| `rotes_construction` | **`fleet`** | логбук: trips, leads, fuel, vehicles | `fleet_rw` (n8n), `fleet_ro` (Metabase) |

Схема `fleet` свідомо лежить у бізнес-базі, поруч із `projects`, `estimates`,
`invoices_snapshot`. Це означає, що логбук переживає будь-яку переустановку
Traccar, а n8n читає поїздки через REST API Traccar, а не з чужої бази.

Підключення — `sslmode=require`, авторизація `scram-sha-256`.

## Firewall

Інфраструктура має явні per-container правила (`policy_in: DROP`), тож
доступ треба відкривати руками. Додано:

```
# /etc/pve/firewall/415.fw
IN ACCEPT -p tcp -dport 5432 -source 192.168.2.66

# /etc/pve/firewall/426.fw  (створено)
[OPTIONS]
enable: 1
policy_in: DROP
policy_out: ACCEPT
log_level_in: warning

[RULES]
GROUP sg-icmp
GROUP sg-ssh-admin
GROUP sg-monitoring
IN ACCEPT -p tcp -dport 8082 -source 192.168.2.48
IN ACCEPT -p tcp -dport 8082 -source 192.168.2.0/24
IN ACCEPT -p tcp -dport 5027 -source 192.168.2.0/24
```

Traccar відкриває **249** протокольних портів усередині контейнера — усі
підтримувані протоколи. Назовні firewall пускає лише 8082 і 5027.

## Запуск з нуля

```bash
# на pve під root
B=https://raw.githubusercontent.com/Rumataistorsky/oracle-a1-disabled-bypass/claude/corporate-vehicle-logbook-6fu6mq/vehicle-logbook
curl -fsSL -o /root/fleet-schema.sql $B/04-data-model.sql
curl -fsSL -o /root/10-database.sh    $B/deploy/10-database.sh
curl -fsSL -o /root/20-traccar.sh     $B/deploy/20-traccar.sh
curl -fsSL -o /root/30-traccar-admin.sh $B/deploy/30-traccar-admin.sh

bash /root/10-database.sh       # ролі, бази, схема fleet, pg_hba
bash /root/20-traccar.sh        # завантаження, конфіг, запуск
bash /root/30-traccar-admin.sh  # адміністратор
```

Паролі генеруються на хості й **не друкуються**. Вони лягають у
`/root/fleet-credentials.txt` (chmod 600) на pve.

> ⚠️ **Перенести вміст `/root/fleet-credentials.txt` у Vaultwarden (VM 103)
> і видалити файл.** Це єдина незакрита дія після розгортання.

### Пастка при створенні першого адміністратора

`POST /api/users` з `"administrator": true` падає з NPE, доки жодного
адміністратора не існує (`PermissionsService.checkAdmin` розіменовує null).
Traccar сам призначає **першого** створеного користувача адміністратором,
тому поле передавати не треба зовсім.

`web.registration` вмикається лише на час створення користувача і
повертається у `false` через `trap ... EXIT`.

## Конфігурація

`/opt/traccar/conf/traccar.xml`, ключові відхилення від дефолту:

```xml
<entry key='web.registration'>false</entry>

<entry key='geocoder.enable'>true</entry>          <!-- адреса підставляється сама -->
<entry key='geocoder.type'>nominatim</entry>
<entry key='geocoder.onRequest'>false</entry>
<entry key='geocoder.reuseDistance'>50</entry>

<entry key='report.trip.minimalTripDistance'>300</entry>
<entry key='report.trip.minimalTripDuration'>120</entry>
<entry key='report.trip.minimalParkingDuration'>60</entry>
<entry key='report.trip.minimalNoDataDuration'>900</entry>  <!-- не подіяло, див. нижче -->
<entry key='report.trip.useIgnition'>false</entry>   <!-- див. нижче -->

<entry key='filter.enable'>true</entry>            <!-- сміття не має потрапляти -->
<entry key='filter.invalid'>true</entry>           <!-- у податковий облік -->
<entry key='filter.zero'>true</entry>
<entry key='filter.duplicate'>true</entry>
<entry key='filter.accuracy'>50</entry>       <!-- див. нижче -->
<!-- filter.distance свідомо вимкнено -->

<entry key='database.positionsHistoryDays'>0</entry> <!-- не видаляти історію -->
```

`positionsHistoryDays=0` критичний: логбук зберігається сім років, автоматичне
підчищення позицій знищило б доказову базу.

### `useIgnition=false` — не косметика

Traccar нарізає поїздки за одним сигналом: `useIgnition=true` → дивиться лише
атрибут `ignition`, `false` → лише `motion`. Телефон-міст шле osmand-пакет без
`ignition`, тому при `true` кожна позиція читалася як «запалення вимкнене»:
`/api/reports/trips` повертав `[]` — порожній масив, HTTP 200, жодної помилки в
логах. Поїздки їздилися, позиції писалися, `fleet.trips` лишалася порожня.

Teltonika FMM003 через OBD шле і `ignition`, і `motion`, тож `false` коректний
і після переходу на залізний трекер. Якщо колись знадобиться саме запалення —
вмикати не глобально, а атрибутом конкретного пристрою.

### Провал звʼязку зшивається в одну «поїздку»

Коли телефон засинає на стоянці, Traccar не бачить розриву: остання точка
перед сном має `motion=true`, наступна приходить за пів доби вже в іншому
місці — і між ними будується одна поїздка. Реальний приклад: `00:07 → 14:05`,
838 хвилин на 6.33 км.

`report.trip.minimalNoDataDuration=900` мав би розривати поїздку на такому
провалі. Ключ у збірці 6.15.3 присутній (`Keys.class`, `TripsConfig.class`),
але після перезапуску звіт лишився незмінним — налаштування не подіяло.
Причину не зʼясовано, ключ лишили на місці як нешкідливий.

Тому захист стоїть у класифікаторі n8n: поїздка довша за 180 хв із середньою
швидкістю під 10 км/год дістає `review_flag` з поясненням. Такий рядок не
потрапляє в звіт мовчки — його видно й треба розібрати вручну. Для CRA це
принципово: один абсурдний рядок ставить під сумнів увесь журнал.

### `filter.accuracy` — без нього журнал сам собі домальовує кілометри

Стоячи на місці, телефон зрідка віддає точку з похибкою 60-180 м. Координата
стрибає на 300-400 м убік і наступним пакетом повертається назад. Traccar
додає обидва стрибки до пройденої відстані, і на стоянці народжується
«поїздка»: 0.5-1.1 км за чотири хвилини, старт і фініш в одній точці.
17.09 за дві години стоянки таких рейсів було шість.

`filter.accuracy=50` відкидає ці точки на вході. Швидкість при цьому нульова,
а `motion` — false, тож жоден поріг із `report.trip.*` їх не ловив.

Другий рубіж стоїть у класифікаторі n8n: якщо пряма відстань між стартом і
фінішем менша за 250 м, а «пройдено» менше 2 км — поїздка не записується
взагалі. Він потрібен, бо вже збережені позиції фільтр не чистить.

### `filter.distance` не вмикати

Traccar розпізнає стоянку саме зі стаціонарних точок. `filter.distance=20`
відкидає їх як «зайві» — і стоянка зникає разом із межею між поїздками.

Публічний Nominatim має жорсткий rate limit. Для одного авто вистачає, але
якщо машин стане більше — власний інстанс або платний геокодер.

## Публікація

Caddy (LXC 514), окремий блок після wildcard `*.rotes.ca`:

```
fleet.rotes.ca {
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	reverse_proxy 192.168.2.66:8082
}
```

DNS у Pi-hole (LXC 202): `/etc/pihole/custom.list` і
`/etc/dnsmasq.d/99-homelab-custom.conf` → `192.168.2.48`.

**Authentik forward-auth не ставити.** Він ламає мобільний застосунок Traccar
і API-клієнтів, бо вони не проходять інтерактивний OIDC-редірект. Якщо потрібен
SSO — підключати Authentik як OpenID-провайдера всередині Traccar (`openid.*`).

## Приймання даних від трекера

Протокольні порти — сирий TCP, Cloudflare Tunnel їх не проксює (потрібен
платний Spectrum). Коли приїде FMM003:

**Варіант A (рекомендовано)** — релей через Hetzner `159.69.142.177`,
далі у mesh `100.64.0.0/10` до LXC 426. Домашній IP не світиться, зміна IP
від Bell нічого не ламає. LXC 426 треба додати у mesh як spoke — так само,
як зроблено для mailcow (601) і sim7600 (423).

```nginx
# /etc/nginx/nginx.conf на Hetzner
stream {
    server {
        listen 5027;
        proxy_pass 100.64.0.X:5027;
        proxy_timeout 10m;
    }
}
```

**Варіант B** — port forward на OpenWRT (VM 210): `WAN:5027 → 192.168.2.66:5027`.
Простіше, але відкриває домашній IP.

Діагностика:

```bash
pct exec 426 -- tail -f /opt/traccar/logs/tracker-server.log
```

## Моніторинг

Prometheus (LXC 900, 192.168.2.33) — додано обидва таргети, перевірено:

```
up{host="traccar", ctid="426"}                = 1
probe_success{instance="https://fleet.rotes.ca"} = 1
```

Алерт «пристрій мовчить довше 36 год» реалізується в n8n (`05`), бо це
бізнес-логіка, а не інфраструктурна метрика. Це найважливіший алерт у системі:
тиха втрата даних руйнує base year, а не разові помилки класифікації.

Uptime Kuma (LXC 901) — **додати вручну**, її API працює через socket.io.

## Бекап

`/opt/pg-backup/pg-backup.sh` на LXC 415 (systemd timer, щодня о 02:00):

* повний `pg_dumpall` уже покривав нові дані з першого дня;
* у явний перелік баз додано `rotes_construction` і `traccar` — для зручного
  відновлення однієї бази;
* offsite-синхронізація на Hetzner Storage Box.

`KEEP_DAYS=7` — це ротація дампів, а не строк зберігання логбука. Сім років
зберігаються **річні PDF/CSV-експорти в Nextcloud** (`06-reporting.md`),
і саме вони є документом для CRA.

## Geofences

Класифікатор дивиться лише на **префікс імені**, тому назва — це не підпис,
а правило: `HOME-OFFICE`, `SHOP-`, `CLIENT-`, `SUPPLIER-`, `SERVICE-`, `GOV-`
дають business, `PERSONAL-` дає personal. Щоб завести нове місце, достатньо додати geofence
з правильним префіксом — код чіпати не треба.

| # | Назва | Центр | R, м | Що це |
|---|-------|-------|------|-------|
| 1 | `SHOP-102-BLOOR` | 45.9782719, -66.6447402 | 120 | орендований воркшоп |
| 2 | `HOME-OFFICE` | 45.9547008, -66.6496588 | 150 | 501 Dundonald St, юридична адреса |
| 3 | `SUPPLIER-RETAIL-SOUTH` | 45.9283033, -66.6624333 | 350 | Home Depot + Costco + Princess Auto |
| 4 | `SUPPLIER-KENT` | 45.93838, -66.66668 | 150 | Kent Building Supplies |
| 5 | `SUPPLIER-TWO-NATIONS` | 45.9877725, -66.627988 | 260 | Two Nations Crossing, Canadian Tire |
| 6 | `SUPPLIER-SUPERSTORE-SMYTHE` | 45.9584767, -66.657964 | 150 | Atlantic Superstore Smythe St |
| 7 | `SUPPLIER-SUPERSTORE-MAIN` | 45.9781423, -66.6575621 | 150 | Atlantic Superstore Main St |
| 8 | `CLIENT-DUNCAN-CROWTHER` | 45.9317769, -66.6583052 | 120 | робоче місце Duncan, прорахунки |
| 9 | `CLIENT-DUNCAN-MARLBOROUGH` | 45.959936, -66.673496 | 120 | 67 Marlborough Dr, дім Duncan |
| 10 | `CLIENT-ROMAN-MARUSIIA` | 45.962166, -66.6915 | 150 | 485 Golf Club Rd, активний проєкт |
| 11 | `CLIENT-KILCLINE-WETMORE` | 45.92623, -66.629709 | 150 | Albert Kilcline, 675 Wetmore Rd |
| 12 | `CLIENT-LI-JAFFREY` | 45.972497, -66.635579 | 150 | LI CHANGHUA, 125 Jaffrey St |
| 13 | `CLIENT-XIN-QI-HUNTINGDON` | 45.925888, -66.63593 | 150 | Xin and Qi, 25 Huntingdon Cir |
| 14 | `CLIENT-UBEH-CENTENNIAL` | 45.979886, -66.598197 | 150 | Promise Ubeh, 12 Centennial Ct |
| 15 | `CLIENT-CCNB-BATHURST` | 47.623035, -65.668696 | 300 | CCNB, Bathurst, 250 км |
| 16 | `CLIENT-UTIMUS-PETERBOROUGH` | 44.309589, -78.330859 | 150 | Utimus, Peterborough ON |
| 17 | `CLIENT-MCDONALD-WATERLOO` | 45.954496, -66.632933 | 120 | Brian McDonald, 58 Waterloo Row |
| 18 | `CLIENT-ITOAFA-SQUIRES` | 45.947974, -66.653104 | 120 | Bogdan George Itoafa, 528 Squires St |
| 19 | `SUPPLIER-SHAW-ALISON` | 45.89628, -66.609484 | 200 | The Shaw Group, 1205 Alison Blvd — бетонні вироби |
| 20 | `SUPPLIER-SPRINGHILL` | 45.96117, -66.742632 | 300 | Springhill Infrastructure, 900 Springhill — щебінь, камінь |
| 21 | `SERVICE-RECAR-AVONLEA` | 45.94505, -66.68941 | 120 | REcar, 14 Avonlea Ct — документи на авто, сервіс |
| 22 | `GOV-CITY-FREDERICTON` | 45.993911, -66.652371 | 150 | City of Fredericton, Reynolds St — реєстрація, номери |

№19-22 додані 23.09.2026 з реальних стоянок того дня: координати —
середнє по точках зі швидкістю <2 вузли (63, 26, 16 і 34 фікси відповідно),
тож центр стоїть рівно там, де авто справді стояло.

`SERVICE-` і `GOV-` — нові префікси. Сервіс власного авто компанії і
оформлення номерів це бізнес-поїздки, але не постачальник і не клієнт,
тому для них окремі категорії.

Центри 1-8 і 10 взяті з **реальних GPS-точок стоянки**, а не з геокодера:
OSM ставить точку Canadian Tire за 200-350 м від місця, де авто справді
стоїть, і geofence просто ніколи не спрацьовує.

№9 — виняток: будинку 67 у OSM немає, центр узято з центроїда вулиці.
Радіус 250 м навмисно широкий; звузити після першого реального виїзду.

Там, де OSM знає **номер будинку**, геокодер виявився точним: для 528 Squires
St його точка лягла за 5 м від координати, яку Роман дав з місця. Промахи
дає лише пошук без номера — тоді повертається центроїд вулиці, а він може
бути за сотні метрів (67 Marlborough: 169 м).

Клієнти 11-16 заведені з адрес в Invoice Ninja. Для 11, 12, 13 і 16 OSM знає
номер будинку, тож центр точний. Для 14 і 15 знайдено лише вулицю — центроїд
може промахнутися, звузити після першого реального виїзду.

Brian McDonald адреси в Invoice Ninja не має взагалі — тільки пошта й телефон.
Координату (58 Waterloo Row) дав Роман з місця, тому радіус одразу 120 м.

Ще чотири клієнти без адреси в Invoice Ninja: Trevor Wells, Andriy
Volikhovskyy, David Itoafa, Olena Volikhovska. Роман вирішив geofence для них
не заводити — поїздки туди лишатимуться `unclassified` з прапорцем і
класифікуються вручну. Це свідомий вибір, а не пропуск.

Двоє клієнтів geofence **не мають**:

* **Ellen and Roman Mashtalyar**, Academy Ct — OSM такої вулиці не знає;
* **Rosales Tony**, 3516 Route 101, Tracyville — сільська траса, номера в OSM
  немає. Центроїд траси покрив би кілометри дороги, і звичайний проїзд повз
  зараховувався б як візит до клієнта. Краще порожньо, ніж хибно: без
  geofence поїздка лишиться `unclassified` з прапорцем на перевірку.

Обидва чекають на реальну GPS-точку з місця.

`CLIENT-UTIMUS-PETERBOROUGH` і `CLIENT-CCNB-BATHURST` — за 1000 і 250 км.
Хибних спрацювань не дадуть, а якщо туди колись буде виїзд, він одразу
ляже як бізнес.

№10 спершу стояв посередині між двома точками стоянки 17.09 з радіусом
250 м. Роман дав координату з місця, тож центр перенесено на неї, а радіус
звужено до 150 м. Друга точка (Duncan Lane, 315 м) у коло не входить — це
був проїзд по району, а не обʼєкт.

№8 має лише 120 м, бо `SUPPLIER-RETAIL-SOUTH` з радіусом 350 м стоїть за
500 м від нього. Якби обидва були ширші, вони б перетнулися, і поїздка до
клієнта записувалася б як закупівля.

Записи вносяться в `tc_geofences` + `tc_user_geofence` (userid 2). Через
API теж можна, але Traccar відхиляє WKT із зайвим нулем у кінці координати:
`-66.6279880` дає HTTP 400, `-66.627988` проходить.

## Що лишилось зробити руками

- [ ] **Перенести `/root/fleet-credentials.txt` у Vaultwarden і видалити файл**
- [ ] Звузити `CLIENT-MARLBOROUGH-67` за реальними GPS після виїзду
- [ ] Додати `fleet.rotes.ca` в Uptime Kuma
- [ ] Cloudflare DNS + tunnel, якщо потрібен доступ поза домашньою мережею
- [ ] Після отримання FMM003: релей на Hetzner, реєстрація пристрою,
      запис `traccar_device_id` у `fleet.vehicles`

## Перевірено

- [x] LXC стартує при завантаженні, Traccar піднімається після `pct reboot`
- [x] `192.168.2.66` статична, конфлікту немає
- [x] Traccar 6.15.3 працює, 51 таблиця створена
- [x] Схема `fleet` розгорнута, 7 таблиць + 4 вʼюхи, авто внесене
- [x] `https://fleet.rotes.ca` → HTTP 200 з валідним сертифікатом
- [x] Порт 5027 слухає
- [x] Адміністратор створений, реєстрація закрита
- [x] Prometheus бачить обидва таргети
- [x] `pg_dump` обох баз проходить
- [x] 10 geofences заведено, класифікація за префіксом працює
