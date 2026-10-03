/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import com.acme.inventory.domain.StockLevel;
import java.time.Instant;

public record StockLevelResponse(
        long productId,
        String warehouseCode,
        long onHand,
        long reserved,
        long available,
        Instant updatedAt) {

    public static StockLevelResponse from(StockLevel level) {
        return new StockLevelResponse(level.getProductId(), level.getWarehouseCode(), level.getQuantity(),
                level.getReserved(), level.getAvailable(), level.getUpdatedAt());
    }
}
