package com.acme.inventory.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.Instant;

@Entity
@Table(name = "stock_levels",
        uniqueConstraints = @UniqueConstraint(columnNames = {"product_id", "warehouse_code"}))
public class StockLevel {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "product_id", nullable = false)
    private Long productId;

    @Column(name = "warehouse_code", nullable = false, length = 16)
    private String warehouseCode;

    @Column(name = "on_hand", nullable = false)
    private long quantity;

    @Column(nullable = false)
    private long reserved;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected StockLevel() {
    }

    public StockLevel(Long productId, String warehouseCode, Instant now) {
        this.productId = productId;
        this.warehouseCode = warehouseCode;
        this.updatedAt = now;
    }

    public Long getId() {
        return id;
    }

    public Long getProductId() {
        return productId;
    }

    public String getWarehouseCode() {
        return warehouseCode;
    }

    /** Physical quantity on hand, including reserved units. */
    public long getQuantity() {
        return quantity;
    }

    public void setQuantity(long quantity) {
        this.quantity = quantity;
    }

    public long getReserved() {
        return reserved;
    }

    public void setReserved(long reserved) {
        this.reserved = reserved;
    }

    /** Quantity that can still be reserved or shipped. */
    public long getAvailable() {
        return quantity - reserved;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Instant updatedAt) {
        this.updatedAt = updatedAt;
    }
}
