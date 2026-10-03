/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.domain;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class StockMovementTest {

    @Test
    void constructor_copiesIdentityAndQuantitiesOfTheLevel() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 25, 4);

        StockMovement movement = new StockMovement(level, MovementType.RECEIPT, 20, "PO-1", NOW);

        assertThat(movement.getId()).isNull();
        assertThat(movement.getStockLevelId()).isEqualTo(1L);
        assertThat(movement.getProductId()).isEqualTo(10L);
        assertThat(movement.getWarehouseCode()).isEqualTo("BER1");
        assertThat(movement.getType()).isEqualTo(MovementType.RECEIPT);
        assertThat(movement.getQuantity()).isEqualTo(20);
        assertThat(movement.getOnHandAfter()).isEqualTo(25);
        assertThat(movement.getReservedAfter()).isEqualTo(4);
        assertThat(movement.getReference()).isEqualTo("PO-1");
        assertThat(movement.getOccurredAt()).isEqualTo(NOW);
    }

    @Test
    void constructor_isNotAffectedByLaterChangesToTheLevel() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 25, 4);
        StockMovement movement = new StockMovement(level, MovementType.RECEIPT, 20, "PO-1", NOW);

        level.setQuantity(30);
        level.setReserved(6);

        assertThat(movement.getOnHandAfter()).isEqualTo(25);
        assertThat(movement.getReservedAfter()).isEqualTo(4);
    }
}
