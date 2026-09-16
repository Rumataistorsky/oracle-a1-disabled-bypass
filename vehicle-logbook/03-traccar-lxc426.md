# 03 — Розгортання Traccar (LXC 426)

Виконується на `pve` (192.168.2.230). ID **426** вільний станом на 2026-09-16
(перевірено через `pct list`; зайняті 200–203, 211, 300–302, 313, 400–425,
501–523, 601–602, 609, 620–622, 700–701, 800–803, 900–901).

> Перед стартом звірити IP-адреси live — у памʼяті частина записана як `.?`.

## 3.1 Створення контейнера

```bash
# на pve
pct create 426 local:vztmpl/debian-13-standard_13.0-1_amd64.tar.zst \
  --hostname traccar \
  --cores 2 --memory 2048 --swap 512 \
  --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.2.56/24,gw=192.168.2.240 \
  --nameserver 192.168.2.241 \
  --onboot 1 \
  --features nesting=1 \
  --tags fleet,logbook,traccar \
  --unprivileged 1

pct start 426
pct exec 426 -- bash -c 'apt update && apt -y upgrade'
```

Зарезервувати `192.168.2.56` у DHCP на OpenWRT (VM 210), щоб адреса не поплила.

## 3.2 База даних на LXC 415 (rotes-db)

Traccar тримає власні таблиці. Схему `fleet` для нашої логіки створює
`04-data-model.sql` — вона окрема і Traccar її не чіпає.

```bash
pct exec 415 -- su - postgres -c "psql -c \"CREATE USER traccar WITH PASSWORD '<ЗГЕНЕРУВАТИ>';\""
pct exec 415 -- su - postgres -c "psql -c 'CREATE DATABASE traccar OWNER traccar;'"
```

Пароль покласти у Vaultwarden (VM 103), не в git.

Дозволити доступ з 192.168.2.56 у `pg_hba.conf` на LXC 415:

```
host    traccar    traccar    192.168.2.56/32    scram-sha-256
```

## 3.3 Встановлення Traccar

```bash
pct exec 426 -- bash -c 'apt -y install openjdk-17-jre-headless unzip curl'

# Звірити актуальну версію на https://github.com/traccar/traccar/releases
VER=6.9.1
pct exec 426 -- bash -c "
  cd /tmp &&
  curl -fsSLO https://github.com/traccar/traccar/releases/download/v\${VER}/traccar-linux-64-\${VER}.zip &&
  unzip -o traccar-linux-64-\${VER}.zip &&
  ./traccar.run
"
```

## 3.4 Конфігурація

`/opt/traccar/conf/traccar.xml` у LXC 426:

```xml
<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
<properties>
  <entry key='config.default'>./conf/default.xml</entry>

  <entry key='database.driver'>org.postgresql.Driver</entry>
  <entry key='database.url'>jdbc:postgresql://192.168.2.15:5432/traccar</entry>
  <entry key='database.user'>traccar</entry>
  <entry key='database.password'>ВЗЯТИ_З_VAULTWARDEN</entry>

  <!-- веб-інтерфейс слухає лише локально, назовні через Caddy -->
  <entry key='web.port'>8082</entry>

  <!-- зворотне геокодування: адреса підставляється автоматично -->
  <entry key='geocoder.enable'>true</entry>
  <entry key='geocoder.type'>nominatim</entry>
  <entry key='geocoder.url'>https://nominatim.openstreetmap.org/reverse</entry>
  <entry key='geocoder.onRequest'>false</entry>
  <entry key='geocoder.processInvalidPositions'>false</entry>

  <!-- поїздки: під наш сценарій -->
  <entry key='report.trip.minimalTripDistance'>300</entry>
  <entry key='report.trip.minimalTripDuration'>120</entry>
  <entry key='report.trip.minimalParkingDuration'>180</entry>
  <entry key='report.trip.useIgnition'>true</entry>

  <entry key='filter.enable'>true</entry>
  <entry key='filter.invalid'>true</entry>
  <entry key='filter.zero'>true</entry>
  <entry key='filter.duplicate'>true</entry>
  <entry key='filter.distance'>20</entry>

  <entry key='event.enable'>true</entry>
  <entry key='event.ignoreDuplicateAlerts'>true</entry>
</properties>
```

> `192.168.2.15` — адреса LXC 415. **Звірити live**, у памʼяті вона позначена `.?`.

Публічний Nominatim має жорсткий rate limit і заборону масових запитів.
Для одного авто цього достатньо, але коректніше поставити власний інстанс
або платний геокодер. `geocoder.onRequest=false` означає геокодування
при збереженні позиції, не на кожен перегляд.

```bash
pct exec 426 -- systemctl enable --now traccar
pct exec 426 -- systemctl status traccar --no-pager
```

## 3.5 Публікація веб-інтерфейсу

Traccar має власну авторизацію. Через Caddy (LXC 514) публікуємо **лише**
веб-порт 8082. Протокольні порти пристроїв ідуть окремим шляхом (3.6).

У `Caddyfile` на LXC 514:

```
fleet.rotes.ca {
    reverse_proxy 192.168.2.56:8082
    encode gzip
}
```

DNS-запис у Pi-hole (LXC 202) і публікація через tunnel (LXC 405), як інші сервіси.

**Про Authentik (LXC 511):** forward-auth перед Traccar ламає його мобільний
застосунок і API-клієнти, бо вони не проходять інтерактивний OIDC-редірект.
Варіанти: або лишити власну авторизацію Traccar із сильним паролем і 2FA,
або підключити Authentik як OpenID-провайдера всередині самого Traccar
(`openid.*` у конфігу). Forward-auth на весь домен — не робити.

## 3.6 Приймання даних від трекера

Протокольні порти Traccar — це **сирий TCP/UDP**, не HTTP. Cloudflare Tunnel
їх не проксює (для TCP потрібен платний Spectrum). Два робочі шляхи:

### Варіант A — релей через Hetzner (рекомендовано)

Трекер підключається до публічного IP Hetzner (`159.69.142.177`), той
пробрасує TCP у LXC 426 через уже наявний mesh (`100.64.0.0/10`).

Переваги: домашній IP не світиться, зміна IP від Bell нічого не ламає,
трекер завжди має одну сталу адресу.

На Hetzner, `nginx` stream (або socat):

```nginx
# /etc/nginx/nginx.conf
stream {
    server {
        listen 5027;                       # порт протоколу Teltonika
        proxy_pass 100.64.0.X:5027;        # адреса LXC 426 у mesh
        proxy_timeout 10m;
    }
}
```

LXC 426 треба додати у mesh як spoke (так само, як зроблено для mailcow 601
і sim7600 423) і виділити йому адресу `100.64.0.X`.

### Варіант B — port forward на OpenWRT (VM 210)

```
WAN :5027  →  192.168.2.56:5027
```

Простіше, але відкриває домашній IP і залежить від його стабільності.

### Порт пристрою

Teltonika FMM003 працює за протоколом `teltonika` — **порт 5027**. Саме його
проксує релей і саме його вказуємо в конфігураторі Teltonika як адресу сервера.

Діагностика підключення:

```bash
pct exec 426 -- tail -f /opt/traccar/logs/tracker-server.log
```

У логах видно спробу підключення пристрою і те, чи декодер розпарсив пакет.
Якщо пристрій не зʼявляється — перевірити по черзі: чи зареєструвався модем
у мережі (світлодіод), чи правильний APN у конфігураторі, чи відкритий порт
на релеї, чи не ріже трафік firewall на Hetzner.

## 3.7 Geofences

Створити в Traccar (Settings → Geofences). Радіуси — орієнтовні, підбираються
по факту.

| Назва | Тип | Призначення |
|---|---|---|
| `HOME-OFFICE` | коло, 150 м | база; **старт бізнес-поїздки**, не commuting |
| `SUPPLIER-*` | коло, 200 м | Home Depot, лісосклад тощо → авто-класифікація «Робота» |
| `CLIENT-*` | коло, 150 м | підтягуються з Invoice Ninja автоматично (`05`) |
| `PERSONAL-*` | коло, 150 м | супермаркет, школа, спортзал → підсвітка «це особисте?» |

Geofences для клієнтів створює n8n із адрес Invoice Ninja — вручну не заводити.

## 3.8 Моніторинг

Додати у Prometheus на LXC 900:

```yaml
  - job_name: 'traccar-node'
    static_configs:
      - targets: ['192.168.2.56:9100']
        labels: { host: 'traccar', ctid: '426' }

  - job_name: 'traccar-http'
    metrics_path: /probe
    params: { module: [http_2xx] }
    static_configs:
      - targets: ['https://fleet.rotes.ca']
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 192.168.2.33:9115
```

Плюс алерт «пристрій мовчить» — реалізований у n8n (`05`), бо це бізнес-логіка,
а не інфраструктурна метрика.

Додати `fleet.rotes.ca` в Uptime Kuma (LXC 901).

## 3.9 Бекап

Дані логбука підлягають зберіганню **7 років**.

```bash
# на pve — vzdump LXC 426 у стандартній ротації
# на LXC 415 — щоденний pg_dump бази traccar і схеми fleet
pct exec 415 -- su - postgres -c \
  "pg_dump -Fc traccar > /var/backups/pg/traccar_\$(date +%F).dump"
```

Схема `fleet` потрапляє в той самий дамп, що й решта `rotes-db`.
Переконатись, що ці дампи входять в offsite-копію Borg.

## 3.10 Чек-лист приймання

- [ ] LXC 426 стартує при завантаженні (`onboot=1`)
- [ ] `192.168.2.56` зарезервовано в DHCP
- [ ] Traccar піднімається після `pct reboot 426`
- [ ] `fleet.rotes.ca` відкривається ззовні, логін працює
- [ ] Тестовий трекер зʼявився і шле позиції
- [ ] Reverse geocoding підставляє адресу
- [ ] Поїздки ріжуться по запалюванню, а не злипаються
- [ ] Geofence `HOME-OFFICE` спрацьовує на вʼїзд і виїзд
- [ ] Prometheus бачить таргет, Uptime Kuma бачить сайт
- [ ] `pg_dump` бази traccar лягає у бекап і входить у Borg

## Джерела

* [Traccar — GitHub releases](https://github.com/traccar/traccar/releases)
* [Traccar — Supported Devices](https://www.traccar.org/devices/)
* [Traccar — офіційний сайт](https://www.traccar.org/)
