CREATE TABLE stock_levels (
    id             BIGSERIAL   PRIMARY KEY,
    product_id     BIGINT      NOT NULL REFERENCES products (id),
    warehouse_code VARCHAR(16) NOT NULL,
    on_hand        BIGINT      NOT NULL DEFAULT 0,
    reserved       BIGINT      NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_stock_levels_product_warehouse UNIQUE (product_id, warehouse_code),
    CONSTRAINT ck_stock_levels_quantities CHECK (reserved >= 0 AND on_hand >= reserved)
);
