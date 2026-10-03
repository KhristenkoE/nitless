/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import com.acme.inventory.domain.Reservation;
import java.time.Instant;

public record ReservationResponse(
        long id,
        long productId,
        String warehouseCode,
        long quantity,
        String orderReference,
        String status,
        Instant expiresAt) {

    public static ReservationResponse from(Reservation reservation) {
        return new ReservationResponse(reservation.getId(), reservation.getProductId(),
                reservation.getWarehouseCode(), reservation.getQuantity(), reservation.getOrderReference(),
                reservation.getStatus().name(), reservation.getExpiresAt());
    }
}
