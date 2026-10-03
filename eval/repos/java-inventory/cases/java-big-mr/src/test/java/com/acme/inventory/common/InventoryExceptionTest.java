/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class InventoryExceptionTest {

    @Test
    void productNotFound_namesTheProduct() {
        InventoryException ex = new ProductNotFoundException(10L);

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.PRODUCT_NOT_FOUND);
        assertThat(ex).hasMessage("Product 10 not found");
    }

    @Test
    void duplicateSku_namesTheSku() {
        InventoryException ex = new DuplicateSkuException("SKU-1");

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.DUPLICATE_SKU);
        assertThat(ex).hasMessage("A product with SKU SKU-1 already exists");
    }

    @Test
    void stockLevelNotFound_namesProductAndWarehouse() {
        InventoryException ex = new StockLevelNotFoundException(10L, "BER1");

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.STOCK_LEVEL_NOT_FOUND);
        assertThat(ex).hasMessage("No stock of product 10 in warehouse BER1");
    }

    @Test
    void insufficientStock_reportsAvailableAndRequestedQuantity() {
        InventoryException ex = new InsufficientStockException(10L, "BER1", 2, 5);

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.INSUFFICIENT_STOCK);
        assertThat(ex).hasMessage("Insufficient stock of product 10 in BER1: available 2, requested 5");
    }

    @Test
    void reservationNotFound_namesTheReservation() {
        InventoryException ex = new ReservationNotFoundException(7L);

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.RESERVATION_NOT_FOUND);
        assertThat(ex).hasMessage("Reservation 7 not found");
    }

    @Test
    void reservationState_namesCurrentStatusAndRejectedAction() {
        InventoryException ex = new ReservationStateException(7L, "EXPIRED", "released");

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.INVALID_RESERVATION_STATE);
        assertThat(ex).hasMessage("Reservation 7 is EXPIRED and cannot be released");
    }

    @Test
    void invalidRequest_keepsTheGivenMessage() {
        InventoryException ex = new InvalidRequestException("Movement quantity must not be zero");

        assertThat(ex.getErrorCode()).isEqualTo(ErrorCode.INVALID_REQUEST);
        assertThat(ex).hasMessage("Movement quantity must not be zero");
    }
}
