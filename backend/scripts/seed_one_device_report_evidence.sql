-- Seed: 1 device, 1 report, multiple evidence rows.
-- Run after: alembic upgrade head, incident types and locations populated.
-- You can change evidence file_url later with UPDATE statements.
--
-- Usage (from project root or backend):
--   psql -U postgres -d trustbond -f backend/scripts/seed_one_device_report_evidence.sql
-- Or run in pgAdmin/DBeaver (no psql variables used).

-- 1) One device
INSERT INTO devices (
  device_id,
  device_hash,
  first_seen_at,
  total_reports,
  trusted_reports,
  flagged_reports,
  device_trust_score
) VALUES (
  'a0000001-0001-4000-8000-000000000001'::uuid,
  'seed-device-hash-001',
  NOW(),
  1,
  0,
  0,
  50.00
) ON CONFLICT (device_id) DO NOTHING;

-- 2) One report (assumes incident_type_id 1 exists – e.g. Theft from seed_incident_types)
INSERT INTO reports (
  report_id,
  device_id,
  incident_type_id,
  description,
  latitude,
  longitude,
  gps_accuracy,
  rule_status,
  is_flagged
) VALUES (
  'b0000001-0001-4000-8000-000000000001'::uuid,
  'a0000001-0001-4000-8000-000000000001'::uuid,
  1,
  'Sample report for testing – seed data.',
  -1.9440,
  30.0620,
  10.5,
  'pending',
  false
) ON CONFLICT (report_id) DO NOTHING;

-- 3) Multiple evidence rows (placeholder URLs – change later with UPDATE)
INSERT INTO evidence_files (
  evidence_id,
  report_id,
  file_url,
  file_type,
  media_latitude,
  media_longitude,
  captured_at,
  is_live_capture,
  uploaded_at
) VALUES
  (
    'c0000001-0001-4000-8000-000000000001'::uuid,
    'b0000001-0001-4000-8000-000000000001'::uuid,
    '/uploads/evidence/placeholder-photo1.jpg',
    'photo',
    -1.9440,
    30.0620,
    NOW() - INTERVAL '1 hour',
    true,
    NOW()
  ),
  (
    'c0000002-0001-4000-8000-000000000002'::uuid,
    'b0000001-0001-4000-8000-000000000001'::uuid,
    '/uploads/evidence/placeholder-photo2.jpg',
    'photo',
    -1.9441,
    30.0621,
    NOW() - INTERVAL '55 minutes',
    true,
    NOW()
  ),
  (
    'c0000003-0001-4000-8000-000000000003'::uuid,
    'b0000001-0001-4000-8000-000000000001'::uuid,
    '/uploads/evidence/placeholder-video1.mp4',
    'video',
    -1.9440,
    30.0620,
    NOW() - INTERVAL '50 minutes',
    true,
    NOW()
  )
ON CONFLICT (evidence_id) DO NOTHING;

-- Optional: update device total_reports to match
UPDATE devices
SET total_reports = (
  SELECT COUNT(*) FROM reports WHERE device_id = 'a0000001-0001-4000-8000-000000000001'::uuid
)
WHERE device_id = 'a0000001-0001-4000-8000-000000000001'::uuid;

-- To change evidence URLs later, run for example:
-- UPDATE evidence_files SET file_url = 'https://your-cdn.com/evidence/photo1.jpg' WHERE evidence_id = 'c0000001-0001-4000-8000-000000000001'::uuid;
