-- Картки дашборда «Vehicle Logbook». Кожен блок між маркерами --CARD: — окремий
-- запит Metabase. Валідуються скриптом deploy/60-metabase.sh перед створенням.

--CARD:kpi_year
SELECT total_km, business_km, personal_km, unclassified_km, business_pct, trip_count
FROM fleet.v_annual_summary
WHERE tax_year = EXTRACT(YEAR FROM current_date)::int;

--CARD:benefit
SELECT label            AS "Авто",
       tax_year         AS "Рік",
       business_pct     AS "Бізнес %",
       personal_km      AS "Особисті км",
       standby_full     AS "Standby повний",
       reduction_eligible AS "Знижка доступна",
       standby_applicable AS "Standby до сплати",
       operating_benefit  AS "Operating benefit",
       total_benefit      AS "Разом на T4"
FROM fleet.v_taxable_benefit
WHERE tax_year = EXTRACT(YEAR FROM current_date)::int;

--CARD:monthly
SELECT date_trunc('month', trip_date)::date AS "Місяць",
       COALESCE(SUM(distance_km) FILTER (WHERE classification = 'business'), 0) AS "Бізнес",
       COALESCE(SUM(distance_km) FILTER (WHERE classification IN ('personal','commute')), 0) AS "Особисті",
       COALESCE(SUM(distance_km) FILTER (WHERE classification = 'unclassified'), 0) AS "Не класифіковані",
       ROUND(100.0 * COALESCE(SUM(distance_km) FILTER (WHERE classification = 'business'), 0)
             / NULLIF(SUM(distance_km), 0), 1) AS "Бізнес %"
FROM fleet.trips
WHERE trip_date >= date_trunc('year', current_date)
GROUP BY 1
ORDER BY 1;

--CARD:thresholds
SELECT
  business_pct                                   AS "Бізнес %",
  (business_pct >= 50)                           AS "Поріг 50% пройдено",
  personal_km                                    AS "Особисті км",
  (personal_km <= 20004)                         AS "Під лімітом 20 004",
  unclassified_km                                AS "Не класифіковано км",
  (unclassified_km = 0)                          AS "Все класифіковано"
FROM fleet.v_annual_summary
WHERE tax_year = EXTRACT(YEAR FROM current_date)::int;

--CARD:cost_per_km
WITH km AS (
    SELECT date_trunc('month', trip_date)::date AS month, SUM(distance_km) AS km
    FROM fleet.trips GROUP BY 1
), fuel AS (
    SELECT date_trunc('month', occurred_on)::date AS month,
           SUM(total_amount) AS spend, SUM(litres) AS litres
    FROM fleet.fuel_events GROUP BY 1
)
SELECT k.month AS "Місяць", k.km AS "Км", f.spend AS "Пальне $",
       ROUND(f.spend / NULLIF(k.km, 0), 3)        AS "Вартість/км",
       ROUND(100 * f.litres / NULLIF(k.km, 0), 2) AS "Л/100км"
FROM km k LEFT JOIN fuel f USING (month)
ORDER BY k.month;

--CARD:leads
SELECT l.outcome AS "Результат", COUNT(*) AS "Лідів",
       ROUND(COALESCE(SUM(t.km), 0)::numeric, 0) AS "Км витрачено"
FROM fleet.leads l
LEFT JOIN LATERAL (
    SELECT SUM(distance_km) AS km FROM fleet.trips WHERE lead_id = l.id
) t ON true
GROUP BY l.outcome
ORDER BY 2 DESC;

--CARD:reimbursements
SELECT occurred_on AS "Дата", vendor AS "Де", total_amount AS "Сума",
       hst_amount AS "HST", paid_by AS "Хто платив", has_receipt AS "Є чек"
FROM fleet.v_reimbursement_queue;

--CARD:data_quality
SELECT
  (SELECT count(*) FROM fleet.trips
     WHERE classification = 'business' AND (purpose IS NULL OR btrim(purpose) = '')) AS "Бізнес без мети",
  (SELECT count(*) FROM fleet.trips
     WHERE classification = 'business' AND lead_id IS NULL
       AND invoice_ninja_client_id IS NULL AND evidence_photo_count = 0)             AS "Бізнес без доказів",
  (SELECT count(*) FROM fleet.trips WHERE classified_by = 'default')                 AS "Класифіковано дефолтом",
  (SELECT count(*) FROM fleet.trips
     WHERE review_flag AND classified_by IN ('default','rule'))                      AS "Позначено, не переглянуто",
  (SELECT count(*) FROM fleet.fuel_events WHERE receipt_url IS NULL)                 AS "Заправок без чека";

--CARD:cra_logbook
SELECT * FROM fleet.v_cra_logbook;
