-- Create application roles if they don't already exist
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trustbond_app') THEN
    CREATE ROLE trustbond_app;
  END IF;
END
$$;
