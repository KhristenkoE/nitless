CREATE TABLE reservations (
    id              BIGSERIAL   PRIMARY KEY,
    product_id      BIGINT      NOT NULL REFERENCES products (id),
    warehouse_code  VARCHAR(16) NOT NULL,
    quantity        BIGINT      NOT NULL CHECK (quantity > 0),
    order_reference VARCHAR(64) NOT NULL,
    status          VARCHAR(16) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_reservations_status_expires ON reservations (status, expires_at);
