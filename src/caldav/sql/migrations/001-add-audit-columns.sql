-- Add audit tracking columns to calendarobjects table.
-- Tracks which channel created an event, and who created/modified it.
-- Idempotent: safe to run multiple times.

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM information_schema.columns
    WHERE table_name='calendarobjects' AND column_name='channel_id') THEN
    ALTER TABLE calendarobjects ADD COLUMN channel_id UUID;
    ALTER TABLE calendarobjects ADD COLUMN created_by VARCHAR(255);
    ALTER TABLE calendarobjects ADD COLUMN modified_by VARCHAR(255);
    ALTER TABLE calendarobjects ADD COLUMN created_at BIGINT;
    ALTER TABLE calendarobjects ADD COLUMN modified_by_at BIGINT;
    CREATE INDEX idx_calendarobjects_channel_id ON calendarobjects(channel_id);
    CREATE INDEX idx_calendarobjects_created_by ON calendarobjects(created_by);
  END IF;
END $$;
