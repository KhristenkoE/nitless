package com.acme.inventory.domain;

import com.acme.inventory.common.ReservationStateException;
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
@Table(name = "reservations")
public class Reservation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "product_id", nullable = false)
    private Long productId;

    @Column(name = "warehouse_code", nullable = false, length = 16)
    private String warehouseCode;

    @Column(nullable = false)
    private long quantity;

    @Column(name = "order_reference", nullable = false, length = 64)
    private String orderReference;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private ReservationStatus status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at", nullable = false)
    private Instant expiresAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected Reservation() {
    }

    public Reservation(Long productId, String warehouseCode, long quantity, String orderReference,
                       Instant now, Instant expiresAt) {
        this.productId = productId;
        this.warehouseCode = warehouseCode;
        this.quantity = quantity;
        this.orderReference = orderReference;
        this.status = ReservationStatus.ACTIVE;
        this.createdAt = now;
        this.expiresAt = expiresAt;
        this.updatedAt = now;
    }

    public void release(Instant now) {
        transitionTo(ReservationStatus.RELEASED, "released", now);
    }

    public void fulfill(Instant now) {
        transitionTo(ReservationStatus.FULFILLED, "fulfilled", now);
    }

    public void expire(Instant now) {
        transitionTo(ReservationStatus.EXPIRED, "expired", now);
    }

    public boolean isActive() {
        return status == ReservationStatus.ACTIVE;
    }

    private void transitionTo(ReservationStatus target, String action, Instant now) {
        if (!isActive()) {
            throw new ReservationStateException(id, status.name(), action);
        }
        this.status = target;
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

    public long getQuantity() {
        return quantity;
    }

    public String getOrderReference() {
        return orderReference;
    }

    public ReservationStatus getStatus() {
        return status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
