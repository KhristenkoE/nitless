/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.domain;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class StockLevelTest {

    @Test
    void constructor_startsWithoutStock() {
        StockLevel level = new StockLevel(10L, "BER1", NOW);

        assertThat(level.getId()).isNull();
        assertThat(level.getProductId()).isEqualTo(10L);
        assertThat(level.getWarehouseCode()).isEqualTo("BER1");
        assertThat(level.getQuantity()).isZero();
        assertThat(level.getReserved()).isZero();
        assertThat(level.getAvailable()).isZero();
        assertThat(level.getUpdatedAt()).isEqualTo(NOW);
    }

    @Test
    void getAvailable_excludesReservedUnits() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 4);

        assertThat(level.getAvailable()).isEqualTo(6);
    }

    @Test
    void getAvailable_isZeroWhenEverythingIsReserved() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 10);

        assertThat(level.getAvailable()).isZero();
    }

    @Test
    void getAvailable_followsChangesToOnHandAndReserved() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 4);

        level.setQuantity(15);
        level.setReserved(7);

        assertThat(level.getAvailable()).isEqualTo(8);
    }
}
