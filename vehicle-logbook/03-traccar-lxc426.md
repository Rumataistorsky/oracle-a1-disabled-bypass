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

## Що лишилось зробити руками

- [ ] **Перенести `/root/fleet-credentials.txt` у Vaultwarden і видалити файл**
- [ ] Geofence `HOME-OFFICE` — потрібна домашня адреса
- [ ] Geofences `SUPPLIER-*` — Home Depot, лісосклад тощо
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
