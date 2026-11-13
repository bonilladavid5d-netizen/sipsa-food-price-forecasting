-- Strict as-observed snapshot query. :origin is an ISO timestamp in UTC.
-- No historical vintage is fabricated from month or HTTP Last-Modified.
WITH known AS (
 SELECT *, ROW_NUMBER() OVER (
  PARTITION BY product_id,market_id,month ORDER BY first_seen_at DESC,snapshot_id DESC
 ) AS rn
 FROM supply_month
 WHERE first_seen_at <= :origin AND month < substr(:origin,1,7)
)
SELECT product_id,market_id,month,snapshot_id,kg
FROM known WHERE rn=1
ORDER BY product_id,market_id,month;
