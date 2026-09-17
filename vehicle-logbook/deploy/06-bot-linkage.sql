-- =====================================================================
-- Звʼязок повідомлень бота з поїздками.
--
-- Картка поїздки живе в Telegram як окреме повідомлення. Щоб відповідь
-- «мета поїздки» знайшла свою поїздку, зберігаємо message_id картки:
-- reply_to_message_id у відповіді вказує рівно на нього.
-- =====================================================================

SET search_path TO fleet, public;

ALTER TABLE trips ADD COLUMN IF NOT EXISTS telegram_message_id bigint;
CREATE INDEX IF NOT EXISTS trips_tg_msg_idx
    ON trips (telegram_message_id) WHERE telegram_message_id IS NOT NULL;

COMMENT ON COLUMN trips.telegram_message_id IS
  'message_id картки в групі. Відповідь на неї задає purpose.';

-- Фото обʼєктів і чеків. Координати НЕ беремо з EXIF (Telegram його зрізає) —
-- телефон в авто є трекером, тож позицію знаходимо в Traccar за часом знімка.
-- Серверний запис надійніший за клієнтські метадані.
CREATE TABLE IF NOT EXISTS photos (
    id              bigserial PRIMARY KEY,
    kind            text NOT NULL DEFAULT 'site'
                      CHECK (kind IN ('site','odometer','receipt','other')),
    taken_at        timestamptz NOT NULL,
    telegram_file_id text NOT NULL UNIQUE,
    from_tg_user_id bigint,
    driver_id       int REFERENCES drivers(id),
    trip_id         bigint REFERENCES trips(id),
    lead_id         bigint REFERENCES leads(id),
    latitude        double precision,
    longitude       double precision,
    zone_name       text,
    storage_url     text,
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS photos_taken_idx ON photos (taken_at);
CREATE INDEX IF NOT EXISTS photos_trip_idx  ON photos (trip_id);

-- Поїздка, що накриває момент часу — щоб привʼязати фото до неї.
CREATE OR REPLACE FUNCTION fleet.trip_at(
    p_vehicle_id int, p_at timestamptz
) RETURNS bigint AS $$
    SELECT id FROM fleet.trips
     WHERE vehicle_id = p_vehicle_id
       AND started_at <= p_at
       AND ended_at   >= p_at - interval '30 minutes'
     ORDER BY started_at DESC
     LIMIT 1;
$$ LANGUAGE sql STABLE;

-- Скільки доказів має бізнес-поїздка (для контролю якості у звіті)
CREATE OR REPLACE FUNCTION fleet.refresh_photo_counts() RETURNS void AS $$
    UPDATE fleet.trips t
       SET evidence_photo_count = COALESCE(p.n, 0)
      FROM (SELECT trip_id, count(*) AS n FROM fleet.photos
             WHERE trip_id IS NOT NULL GROUP BY trip_id) p
     WHERE p.trip_id = t.id
       AND t.evidence_photo_count IS DISTINCT FROM p.n;
$$ LANGUAGE sql;
