CREATE TABLE stock_movements (
    id             BIGSERIAL    PRIMARY KEY,
    stock_level_id BIGINT       NOT NULL REFERENCES stock_levels (id),
    product_id     BIGINT       NOT NULL,
    warehouse_code VARCHAR(16)  NOT NULL,
    movement_type  VARCHAR(32)  NOT NULL,
    quantity       BIGINT       NOT NULL,
    on_hand_after  BIGINT       NOT NULL,
    reserved_after BIGINT       NOT NULL,
    reference      VARCHAR(128) NOT NULL,
    occurred_at    TIMESTAMPTZ  NOT NULL
);

CREATE INDEX ix_stock_movements_product_occurred ON stock_movements (product_id, occurred_at DESC);
