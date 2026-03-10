-- Add context_tags to reports (one or more contextual tags from the mobile app, e.g. Night-time, Weapons involved).
-- Run this against your database if you applied schema from trustbond_backup.sql which does not include context_tags.

ALTER TABLE public.reports
ADD COLUMN IF NOT EXISTS context_tags TEXT[] DEFAULT '{}';

COMMENT ON COLUMN public.reports.context_tags IS 'Contextual tags from reporter (e.g. Night-time, Weapons involved, Multiple suspects).';
