CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email       text NOT NULL UNIQUE,
  name        text NOT NULL,
  role        text NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'staff', 'admin')),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  token_hash  text PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  expires_at  timestamptz NOT NULL
);

CREATE TABLE rooms (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                  text NOT NULL UNIQUE,
  capacity              integer NOT NULL CHECK (capacity > 0),
  hourly_rate_cents     integer NOT NULL CHECK (hourly_rate_cents >= 0),
  currency              char(3) NOT NULL DEFAULT 'EUR',
  max_duration_minutes  integer NOT NULL DEFAULT 240,
  active                boolean NOT NULL DEFAULT true
);

CREATE TABLE bookings (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id       uuid NOT NULL REFERENCES rooms (id),
  user_id       uuid NOT NULL REFERENCES users (id),
  title         text NOT NULL,
  starts_at     timestamptz NOT NULL,
  ends_at       timestamptz NOT NULL,
  status        text NOT NULL DEFAULT 'confirmed'
                  CHECK (status IN ('confirmed', 'checked_in', 'cancelled')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  cancelled_at  timestamptz,
  CHECK (ends_at > starts_at)
);

CREATE INDEX bookings_room_time_idx ON bookings (room_id, starts_at);
CREATE INDEX bookings_user_idx ON bookings (user_id, starts_at);

CREATE TABLE audit_events (
  id          bigserial PRIMARY KEY,
  type        text NOT NULL,
  actor_id    uuid NOT NULL,
  subject_id  text NOT NULL,
  meta        jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outbox (
  id          bigserial PRIMARY KEY,
  topic       text NOT NULL,
  payload     jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  sent_at     timestamptz
);
