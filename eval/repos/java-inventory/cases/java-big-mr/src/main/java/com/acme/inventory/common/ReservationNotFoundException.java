/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

public class ReservationNotFoundException extends InventoryException {

    public ReservationNotFoundException(long reservationId) {
        super(ErrorCode.RESERVATION_NOT_FOUND, "Reservation " + reservationId + " not found");
    }
}
