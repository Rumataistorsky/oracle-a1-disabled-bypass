SELECT
  (SELECT count(*) FROM fleet.vehicles WHERE traccar_device_id IS NOT NULL) AS expected_devices,
  (SELECT chat_id FROM fleet.drivers WHERE role='owner' AND active LIMIT 1) AS chat_id,
  (SELECT count(*) FROM fleet.trips
     WHERE classification='unclassified' AND started_at < now() - interval '72 hours') AS stale_unclassified,
  (SELECT coalesce(sum(distance_km),0) FROM fleet.trips
     WHERE classification='unclassified') AS unclassified_km,
  (SELECT count(*) FROM fleet.trips
     WHERE classification='business' AND (purpose IS NULL OR btrim(purpose)='')) AS business_no_purpose,
  (SELECT count(*) FROM fleet.fuel_events
     WHERE paid_by <> 'corporate_card' AND reimbursement_status IN ('pending','submitted')) AS pending_reimbursements,
  (SELECT count(*) FROM fleet.fuel_events
     WHERE receipt_url IS NULL) AS fuel_without_receipt,
  (SELECT coalesce(sum(distance_km),0) FROM fleet.trips
     WHERE trip_date > coalesce((SELECT max(occurred_on) FROM fleet.fuel_events), date '1970-01-01')) AS km_since_last_fuel,
  (SELECT count(*) FROM fleet.odometer_readings
     WHERE reason='year_end' AND extract(year from read_on)=extract(year from current_date)) AS have_year_end;
