-- =====================================================================
-- Атрибуція водія, коли інтерфейсом логбука є спільний телефон в авто.
--
-- Проблема: callback_query дає telegram user_id того, хто натиснув. Якщо
-- кнопки тисне спільний апарат, id завжди один, і поїздки неможливо
-- розвести по людях. А standby charge і operating benefit рахуються
-- окремо по кожному водію і йдуть у різні T4.
--
-- Рішення: «хто за кермом» — це стан (зміна), а не поле кожної поїздки.
-- Натискання з особистого акаунта атрибутується напряму; натискання зі
-- спільного апарата — за активною зміною.
-- =====================================================================

SET search_path TO fleet, public;

ALTER TABLE drivers ADD COLUMN IF NOT EXISTS telegram_user_id bigint;
CREATE UNIQUE INDEX IF NOT EXISTS drivers_tg_uid_idx
    ON drivers (telegram_user_id) WHERE telegram_user_id IS NOT NULL;

COMMENT ON COLUMN drivers.telegram_user_id IS
  'Особистий Telegram-акаунт. Натискання звідси атрибутується прямо цій людині.';

-- Спільні апарати: телефон в авто тощо. Натискання звідси НЕ ідентифікують людину.
CREATE TABLE IF NOT EXISTS shared_devices (
    telegram_user_id bigint PRIMARY KEY,
    label            text NOT NULL,
    vehicle_id       int REFERENCES vehicles(id),
    note             text
);

-- Зміни за кермом. Відкрита зміна — та, де ended_at IS NULL.
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

-- Відкрити зміну: попередню закриваємо тим самим моментом, щоб не було дірок
-- і перекриттів у часовій лінії.
CREATE OR REPLACE FUNCTION fleet.open_shift(
    p_vehicle_id int, p_driver_id int, p_set_by bigint DEFAULT NULL
) RETURNS bigint AS $$
DECLARE
    v_now timestamptz := now();
    v_id  bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM driver_shifts
                WHERE vehicle_id = p_vehicle_id AND ended_at IS NULL
                  AND driver_id = p_driver_id) THEN
        SELECT id INTO v_id FROM driver_shifts
         WHERE vehicle_id = p_vehicle_id AND ended_at IS NULL AND driver_id = p_driver_id;
        RETURN v_id;   -- уже за кермом, нічого не міняємо
    END IF;

    UPDATE driver_shifts SET ended_at = v_now
     WHERE vehicle_id = p_vehicle_id AND ended_at IS NULL;

    INSERT INTO driver_shifts (vehicle_id, driver_id, started_at, set_by_tg_id)
    VALUES (p_vehicle_id, p_driver_id, v_now, p_set_by)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$ LANGUAGE plpgsql;

-- Хто був за кермом у конкретний момент. Якщо зміну не відкривали — власник,
-- бо авто оформлене на компанію і за замовчуванням ним керує він.
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

CREATE OR REPLACE VIEW v_current_driver AS
SELECT v.id AS vehicle_id, v.label AS vehicle,
       d.id AS driver_id, d.label AS driver,
       s.started_at AS since
FROM vehicles v
LEFT JOIN driver_shifts s ON s.vehicle_id = v.id AND s.ended_at IS NULL
LEFT JOIN drivers d ON d.id = COALESCE(s.driver_id,
              (SELECT id FROM drivers WHERE role='owner' AND active ORDER BY id LIMIT 1));

-- Розбивка benefit по людях — саме те, що йде в T4 кожного окремо.
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
