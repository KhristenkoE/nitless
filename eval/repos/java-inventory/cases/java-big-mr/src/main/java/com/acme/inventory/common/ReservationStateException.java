/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

public class ReservationStateException extends InventoryException {

    public ReservationStateException(Long reservationId, String currentStatus, String action) {
        super(ErrorCode.INVALID_RESERVATION_STATE,
                "Reservation " + reservationId + " is " + currentStatus + " and cannot be " + action);
    }
}
