-- =====================================================================
-- Атрибуція водія за Telegram-акаунтом.
--
-- Контекст: Роман тисне кнопки з телефона, що постійно живе в авто
-- (окремий Telegram-акаунт), Алекс — зі свого. Особистий телефон Романа
-- у схемі не бере участі: фото обʼєктів мають іти повз його галерею.
--
-- Отже одна людина може мати кілька акаунтів → мапінг окремою таблицею,
-- а не полем у drivers.
--
-- Зміни за кермом лишаються як запобіжник: якщо натискання прийшло з
-- апарата, не привʼязаного до людини, водій визначається за відкритою
-- зміною. Це важливо, бо standby charge і operating benefit рахуються
-- окремо по кожному і йдуть у різні T4.
-- =====================================================================

SET search_path TO fleet, public;

-- Telegram-акаунти людей. Одна людина — скільки завгодно акаунтів.
CREATE TABLE IF NOT EXISTS driver_accounts (
    telegram_user_id bigint PRIMARY KEY,
    driver_id        int NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    label            text NOT NULL,
    is_device        boolean NOT NULL DEFAULT false,
    note             text
);

CREATE INDEX IF NOT EXISTS driver_accounts_driver_idx ON driver_accounts (driver_id);

COMMENT ON COLUMN driver_accounts.is_device IS
  'true = акаунт живе на апараті, а не при людині (телефон в авто). '
  'Використовується, щоб попередити, якщо за кермом може бути не власник акаунта.';

-- Апарати, які НЕ ідентифікують людину (зараз таких немає, але хай буде).
CREATE TABLE IF NOT EXISTS shared_devices (
    telegram_user_id bigint PRIMARY KEY,
    label            text NOT NULL,
    vehicle_id       int REFERENCES vehicles(id),
    note             text
);

-- Зміни за кермом.
CREATE TABLE IF NOT EXISTS driver_shifts (
    id           bigserial PRIMARY KEY,
    vehicle_id   int NOT NULL REFERENCES vehicles(id),
    driver_id    int NOT NULL REFERENCES drivers(id),
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    set_by_tg_id bigint,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX IF NOT EXISTS driver_shifts_open_idx
    ON driver_shifts (vehicle_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS driver_shifts_span_idx
    ON driver_shifts (vehicle_id, started_at, ended_at);

-- Відкрити зміну: попередню закриваємо тим самим моментом, щоб у часовій
-- лінії не було ні дірок, ні перекриттів.
CREATE OR REPLACE FUNCTION fleet.open_shift(
    p_vehicle_id int, p_driver_id int, p_set_by bigint DEFAULT NULL
) RETURNS bigint AS $$
DECLARE
    v_now timestamptz := now();
    v_id  bigint;
BEGIN
    SELECT id INTO v_id FROM driver_shifts
     WHERE vehicle_id = p_vehicle_id AND ended_at IS NULL AND driver_id = p_driver_id;
    IF FOUND THEN
        RETURN v_id;   -- уже за кермом
    END IF;

    UPDATE driver_shifts SET ended_at = v_now
     WHERE vehicle_id = p_vehicle_id AND ended_at IS NULL;

    INSERT INTO driver_shifts (vehicle_id, driver_id, started_at, set_by_tg_id)
    VALUES (p_vehicle_id, p_driver_id, v_now, p_set_by)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$ LANGUAGE plpgsql;

-- Хто був за кермом у момент p_at.
CREATE OR REPLACE FUNCTION fleet.driver_at(
    p_vehicle_id int, p_at timestamptz
) RETURNS int AS $$
    SELECT COALESCE(
        (SELECT driver_id FROM fleet.driver_shifts
          WHERE vehicle_id = p_vehicle_id
            AND started_at <= p_at
            AND (ended_at IS NULL OR ended_at > p_at)
          ORDER BY started_at DESC LIMIT 1),
        (SELECT id FROM fleet.drivers WHERE role = 'owner' AND active ORDER BY id LIMIT 1)
    );
$$ LANGUAGE sql STABLE;

-- Кому приписати натискання: спершу акаунт, інакше зміна, інакше власник.
CREATE OR REPLACE FUNCTION fleet.driver_for_tap(
    p_vehicle_id int, p_tg_id bigint, p_at timestamptz DEFAULT now()
) RETURNS int AS $$
    SELECT COALESCE(
        (SELECT a.driver_id FROM fleet.driver_accounts a
          WHERE a.telegram_user_id = p_tg_id),
        fleet.driver_at(p_vehicle_id, p_at)
    );
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE VIEW v_current_driver AS
SELECT v.id AS vehicle_id, v.label AS vehicle,
       d.id AS driver_id, d.label AS driver,
       s.started_at AS since
FROM vehicles v
LEFT JOIN driver_shifts s ON s.vehicle_id = v.id AND s.ended_at IS NULL
LEFT JOIN drivers d ON d.id = COALESCE(s.driver_id,
              (SELECT id FROM drivers WHERE role='owner' AND active ORDER BY id LIMIT 1));

-- Розбивка benefit по людях — у T4 кожного окремо.
CREATE OR REPLACE VIEW v_benefit_by_driver AS
SELECT d.label                                   AS driver,
       d.role,
       EXTRACT(YEAR FROM t.trip_date)::int       AS tax_year,
       COALESCE(SUM(t.distance_km), 0)           AS total_km,
       COALESCE(SUM(t.distance_km) FILTER (WHERE t.classification='business'), 0)  AS business_km,
       COALESCE(SUM(t.distance_km) FILTER (WHERE t.classification IN ('personal','commute')), 0) AS personal_km,
       ROUND(0.34 * COALESCE(SUM(t.distance_km)
             FILTER (WHERE t.classification IN ('personal','commute')), 0), 2)     AS operating_benefit
FROM trips t
JOIN drivers d ON d.id = t.driver_id
GROUP BY d.label, d.role, EXTRACT(YEAR FROM t.trip_date);

-- ---------------------------------------------------------------------
-- Реєстрація відомих акаунтів
-- ---------------------------------------------------------------------
INSERT INTO driver_accounts (telegram_user_id, driver_id, label, is_device, note)
SELECT 309249296, id, 'Телефон в авто (@RoRoTes)', true,
       'Постійно в авто: Traccar Client, фото обʼєктів, кнопки логбука. '
       'Особистий телефон Романа у логбуці не використовується.'
FROM drivers WHERE label = 'Roman'
ON CONFLICT (telegram_user_id) DO NOTHING;

INSERT INTO driver_accounts (telegram_user_id, driver_id, label, is_device, note)
SELECT 5318488755, id, 'Особистий Telegram (@RomanTeslaCA)', false,
       'Для адміністрування. Фото обʼєктів сюди не йдуть.'
FROM drivers WHERE label = 'Roman'
ON CONFLICT (telegram_user_id) DO NOTHING;

-- Акаунт Алекса підхопиться автоматично з першого натискання: бот побачить
-- невідомий telegram_user_id від учасника групи і попросить підтвердити.
