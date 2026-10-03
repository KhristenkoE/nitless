/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class StockLevelResponseTest {

    @Test
    void from_exposesOnHandReservedAndAvailableQuantity() {
        StockLevelResponse response = StockLevelResponse.from(stockLevel(1L, 10L, "BER1", 10, 4));

        assertThat(response).isEqualTo(new StockLevelResponse(10L, "BER1", 10, 4, 6, NOW));
    }
}
