-- =====================================================================
-- 04 — Схема `fleet` у PostgreSQL (LXC 415 rotes-db)
-- Source of truth логбука. Traccar лишається джерелом сирих позицій,
-- Invoice Ninja — джерелом грошей. Кілометри живуть тут.
--
--   psql -U postgres -d rotes -f 04-data-model.sql
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS fleet;
SET search_path TO fleet, public;

-- ---------------------------------------------------------------------
-- Довідники
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vehicles (
    id              serial PRIMARY KEY,
    vin             text NOT NULL UNIQUE,
    label           text NOT NULL,
    make_model      text NOT NULL,
    model_year      int  NOT NULL,
    -- вартість з усіма податками — база для standby charge
    original_cost   numeric(12,2) NOT NULL,
    acquired_on     date NOT NULL,
    acquired_odo_km int  NOT NULL,
    traccar_device_id int,          -- id пристрою в Traccar
    is_automobile   boolean NOT NULL DEFAULT true,  -- за ITA 248(1)
    notes           text
);

COMMENT ON COLUMN vehicles.original_cost IS
  'Вартість включно з HST. Standby charge рахується від неї, а не від ліміту CCA.';
COMMENT ON COLUMN vehicles.is_automobile IS
  'true = підпадає під standby charge. Pacifica (7 місць) = true.';

CREATE TABLE IF NOT EXISTS drivers (
    id              serial PRIMARY KEY,
    label           text NOT NULL,
    role            text NOT NULL CHECK (role IN ('owner','employee')),
    -- дім водія = principal place of business? для власника true
    home_is_office  boolean NOT NULL DEFAULT false,
    chat_id         text,           -- Telegram / SimpleX для бота
    active          boolean NOT NULL DEFAULT true
);

COMMENT ON COLUMN drivers.home_is_office IS
  'true → поїздка з дому на обʼєкт є бізнесовою. false → це commuting = особисте.';

-- ---------------------------------------------------------------------
-- Одометр: фото з панелі на початок і кінець року + звірка
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS odometer_readings (
    id              bigserial PRIMARY KEY,
    vehicle_id      int  NOT NULL REFERENCES vehicles(id),
    read_on         date NOT NULL,
    -- Дати замало. Зчитування о 14:07 і поїздки того ж дня по обіді - різні
    -- речі, а по даті вони зливаються, і звірка з GPS показує чужий пробіг.
    read_at         timestamptz NOT NULL DEFAULT now(),
    odometer_km     int  NOT NULL,
    reason          text NOT NULL CHECK (reason IN
                      ('year_start','year_end','acquisition','disposal','spot_check')),
    photo_url       text,           -- Nextcloud / Immich
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (vehicle_id, read_on, reason)
);

-- ---------------------------------------------------------------------
-- Ліди: обʼєкти, куди їздили на оцінку, часто без імені клієнта
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS leads (
    id              bigserial PRIMARY KEY,
    address         text NOT NULL,
    latitude        double precision,
    longitude       double precision,
    first_seen_on   date NOT NULL DEFAULT current_date,
    what_quoted     text,           -- «замір — заміна покрівлі»
    source          text,           -- referral / оголошення / повторний
    outcome         text NOT NULL DEFAULT 'open'
                      CHECK (outcome IN ('open','quoted','won','lost','no_bid')),
    invoice_ninja_client_id  text,  -- зʼявляється після конвертації
    invoice_ninja_quote_id   text,
    immich_album_id text,           -- гео-фото обʼєкта
    notes           text
);

CREATE INDEX IF NOT EXISTS leads_geo_idx ON leads (latitude, longitude);

-- ---------------------------------------------------------------------
-- Поїздки — ядро логбука. Одна поїздка = один запис у формі CRA.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trips (
    id              bigserial PRIMARY KEY,
    vehicle_id      int  NOT NULL REFERENCES vehicles(id),
    driver_id       int  REFERENCES drivers(id),

    -- ідемпотентність: Traccar може віддати ту саму поїздку повторно
    traccar_trip_key text UNIQUE,

    started_at      timestamptz NOT NULL,
    ended_at        timestamptz NOT NULL,

    -- CRA: дата, пункт призначення, мета, км
    trip_date       date NOT NULL,
    origin_address  text NOT NULL,
    destination_address text NOT NULL,
    purpose         text,
    distance_km     numeric(8,2) NOT NULL CHECK (distance_km >= 0),

    -- одометр, якщо пристрій його дає; для Pacifica буде NULL
    odo_start_km    int,
    odo_end_km      int,

    classification  text NOT NULL DEFAULT 'unclassified'
                      CHECK (classification IN
                        ('unclassified','business','personal','commute')),
    -- звідки взялася класифікація
    classified_by   text CHECK (classified_by IN
                        ('geofence','driver','rule','default','manual')),
    classified_at   timestamptz,

    lead_id         bigint REFERENCES leads(id),
    invoice_ninja_client_id text,
    invoice_ninja_project_id text,
    billable        boolean NOT NULL DEFAULT false,

    -- прапорець для поїздок, які схожі на особисті (вихідні, пізній час)
    review_flag     boolean NOT NULL DEFAULT false,
    review_reason   text,

    evidence_photo_count int NOT NULL DEFAULT 0,

    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),

    CHECK (ended_at >= started_at)
);

CREATE INDEX IF NOT EXISTS trips_date_idx    ON trips (vehicle_id, trip_date);
CREATE INDEX IF NOT EXISTS trips_unclass_idx ON trips (classification)
                                             WHERE classification = 'unclassified';
CREATE INDEX IF NOT EXISTS trips_review_idx  ON trips (review_flag) WHERE review_flag;

COMMENT ON COLUMN trips.classification IS
  'commute = дім водія ↔ база, коли дім водія НЕ є офісом. Для CRA це personal, '
  'але тримаємо окремо, щоб бачити природу пробігу.';

-- оновлення updated_at
CREATE OR REPLACE FUNCTION fleet.touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trips_touch ON trips;
CREATE TRIGGER trips_touch BEFORE UPDATE ON trips
    FOR EACH ROW EXECUTE FUNCTION fleet.touch_updated_at();

-- ---------------------------------------------------------------------
-- Пальне і витрати. Ключове поле — хто платив.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fuel_events (
    id              bigserial PRIMARY KEY,
    vehicle_id      int  NOT NULL REFERENCES vehicles(id),
    occurred_on     date NOT NULL,
    odometer_km     int,
    litres          numeric(8,2),
    total_amount    numeric(10,2) NOT NULL,
    hst_amount      numeric(10,2),
    vendor          text,

    paid_by         text NOT NULL CHECK (paid_by IN
                      ('corporate_card','personal_card','cash')),
    -- пряма оплата третій стороні зменшує operating benefit,
    -- але лише за наявності доказу оплати
    receipt_url     text,
    reimbursement_status text NOT NULL DEFAULT 'n_a'
                      CHECK (reimbursement_status IN
                        ('n_a','pending','submitted','reimbursed')),
    invoice_ninja_expense_id text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fuel_pending_idx ON fuel_events (reimbursement_status)
    WHERE reimbursement_status = 'pending';

COMMENT ON COLUMN fuel_events.receipt_url IS
  'Без чека витрата не дає ні вирахування, ні HST ITC, ні зменшення benefit. '
  'Готівка без чека = гроші, подаровані компанії.';

CREATE TABLE IF NOT EXISTS other_costs (
    id              bigserial PRIMARY KEY,
    vehicle_id      int  NOT NULL REFERENCES vehicles(id),
    occurred_on     date NOT NULL,
    category        text NOT NULL,   -- insurance / maintenance / tires / registration / interest
    total_amount    numeric(10,2) NOT NULL,
    hst_amount      numeric(10,2),
    vendor          text,
    paid_by         text NOT NULL CHECK (paid_by IN
                      ('corporate_card','personal_card','cash')),
    receipt_url     text,
    invoice_ninja_expense_id text,
    notes           text
);

-- =====================================================================
-- Подання для звітності
-- =====================================================================

-- Річний підсумок по авто: база для business % і benefit
CREATE OR REPLACE VIEW v_annual_summary AS
SELECT
    t.vehicle_id,
    EXTRACT(YEAR FROM t.trip_date)::int                       AS tax_year,
    -- COALESCE обовʼязковий: FILTER без збігів дає NULL, і тоді розрахунок
    -- benefit тихо схлопується в NULL або в повний standby. Нуль особистих
    -- кілометрів — це нуль, а не «невідомо».
    COALESCE(SUM(t.distance_km), 0)                           AS total_km,
    COALESCE(SUM(t.distance_km) FILTER (WHERE t.classification = 'business'), 0)
                                                              AS business_km,
    COALESCE(SUM(t.distance_km) FILTER (WHERE t.classification IN ('personal','commute')), 0)
                                                              AS personal_km,
    COALESCE(SUM(t.distance_km) FILTER (WHERE t.classification = 'unclassified'), 0)
                                                              AS unclassified_km,
    COALESCE(ROUND(
        100.0 * COALESCE(SUM(t.distance_km) FILTER (WHERE t.classification = 'business'), 0)
        / NULLIF(SUM(t.distance_km), 0), 2), 0)               AS business_pct,
    COUNT(*)                                                  AS trip_count
FROM trips t
GROUP BY t.vehicle_id, EXTRACT(YEAR FROM t.trip_date);

-- Розрахунок taxable benefit. Ставки 2026: operating 34¢, поріг 20 004 км.
CREATE OR REPLACE VIEW v_taxable_benefit AS
WITH s AS (
    SELECT a.*, v.original_cost, v.is_automobile, v.label
    FROM v_annual_summary a
    JOIN vehicles v ON v.id = a.vehicle_id
)
SELECT
    s.vehicle_id,
    s.label,
    s.tax_year,
    s.total_km,
    s.business_km,
    s.personal_km,
    s.business_pct,
    s.unclassified_km,

    -- повний standby: 2% × вартість × 12 періодів
    ROUND(0.02 * s.original_cost * 12, 2)                     AS standby_full,

    -- знижений доступний лише якщо бізнес ≥50% і особистих ≤20 004
    (s.business_pct >= 50 AND s.personal_km <= 20004)         AS reduction_eligible,

    CASE WHEN s.business_pct >= 50 AND s.personal_km <= 20004
         THEN ROUND(0.02 * s.original_cost * 12 * (s.personal_km / 20004.0), 2)
         ELSE ROUND(0.02 * s.original_cost * 12, 2)
    END                                                       AS standby_applicable,

    ROUND(0.34 * s.personal_km, 2)                            AS operating_benefit,

    CASE WHEN s.business_pct >= 50 AND s.personal_km <= 20004
         THEN ROUND(0.02 * s.original_cost * 12 * (s.personal_km / 20004.0)
                    + 0.34 * s.personal_km, 2)
         ELSE ROUND(0.02 * s.original_cost * 12 + 0.34 * s.personal_km, 2)
    END                                                       AS total_benefit
FROM s
WHERE s.is_automobile;

-- Форма логбука для CRA — те, що віддається бухгалтеру
CREATE OR REPLACE VIEW v_cra_logbook AS
SELECT
    t.trip_date                          AS "Date",
    t.origin_address                     AS "From",
    t.destination_address                AS "Destination",
    COALESCE(t.purpose, '')              AS "Purpose",
    t.distance_km                        AS "Kilometres",
    CASE t.classification
        WHEN 'business' THEN 'Business'
        WHEN 'personal' THEN 'Personal'
        WHEN 'commute'  THEN 'Personal (commute)'
        ELSE 'UNCLASSIFIED'
    END                                  AS "Type",
    d.label                              AS "Driver",
    v.label                              AS "Vehicle",
    t.evidence_photo_count               AS "Photos"
FROM trips t
JOIN vehicles v ON v.id = t.vehicle_id
LEFT JOIN drivers d ON d.id = t.driver_id
ORDER BY t.trip_date, t.started_at;

-- Черга невідшкодованих особистих оплат
CREATE OR REPLACE VIEW v_reimbursement_queue AS
SELECT occurred_on, vendor, total_amount, hst_amount, paid_by,
       receipt_url IS NOT NULL AS has_receipt
FROM fuel_events
WHERE paid_by <> 'corporate_card'
  AND reimbursement_status IN ('pending','submitted')
UNION ALL
SELECT occurred_on, vendor, total_amount, hst_amount, paid_by,
       receipt_url IS NOT NULL
FROM other_costs
WHERE paid_by <> 'corporate_card'
ORDER BY occurred_on;

-- =====================================================================
-- Початкові дані
-- =====================================================================

INSERT INTO vehicles (vin, label, make_model, model_year,
                      original_cost, acquired_on, acquired_odo_km, is_automobile, notes)
VALUES ('2C4RC1GGXSR535286', 'Pacifica', 'Chrysler Pacifica Limited', 2025,
        47147.70, '2026-09-16', 47305, true,
        'V6. 7 місць → automobile за ITA 248(1), виключення для van не діє. '
        'Немає в списку OEM-параметрів Teltonika → реального одометра з CAN немає.')
ON CONFLICT (vin) DO NOTHING;

INSERT INTO drivers (label, role, home_is_office)
VALUES ('Roman', 'owner', true)
ON CONFLICT DO NOTHING;

-- Водій: home_is_office = false. Його дім ↔ база = commute = особисте.
-- Найчистіше — авто ночує на базі, тоді у водія особистих км немає взагалі.
-- INSERT INTO drivers (label, role, home_is_office) VALUES ('<імʼя>', 'employee', false);
