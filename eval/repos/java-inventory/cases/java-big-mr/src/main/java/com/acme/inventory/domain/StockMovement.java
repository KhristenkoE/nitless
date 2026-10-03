/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "stock_movements")
public class StockMovement {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "stock_level_id", nullable = false)
    private Long stockLevelId;

    @Column(name = "product_id", nullable = false)
    private Long productId;

    @Column(name = "warehouse_code", nullable = false, length = 16)
    private String warehouseCode;

    @Enumerated(EnumType.STRING)
    @Column(name = "movement_type", nullable = false, length = 32)
    private MovementType type;

    @Column(nullable = false)
    private long quantity;

    @Column(name = "on_hand_after", nullable = false)
    private long onHandAfter;

    @Column(name = "reserved_after", nullable = false)
    private long reservedAfter;

    @Column(nullable = false, length = 128)
    private String reference;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    protected StockMovement() {
    }

    /** Snapshot of a movement; {@code level} must already reflect the movement. */
    public StockMovement(StockLevel level, MovementType type, long quantity, String reference, Instant occurredAt) {
        this.stockLevelId = level.getId();
        this.productId = level.getProductId();
        this.warehouseCode = level.getWarehouseCode();
        this.type = type;
        this.quantity = quantity;
        this.onHandAfter = level.getQuantity();
        this.reservedAfter = level.getReserved();
        this.reference = reference;
        this.occurredAt = occurredAt;
    }

    public Long getId() {
        return id;
    }

    public Long getStockLevelId() {
        return stockLevelId;
    }

    public Long getProductId() {
        return productId;
    }

    public String getWarehouseCode() {
        return warehouseCode;
    }

    public MovementType getType() {
        return type;
    }

    public long getQuantity() {
        return quantity;
    }

    public long getOnHandAfter() {
        return onHandAfter;
    }

    public long getReservedAfter() {
        return reservedAfter;
    }

    public String getReference() {
        return reference;
    }

    public Instant getOccurredAt() {
        return occurredAt;
    }
}
