/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

public record CreateReservationRequest(
        @Positive long productId,
        @NotBlank @Size(max = 16) String warehouseCode,
        @Positive long quantity,
        @NotBlank @Size(max = 64) String orderReference) {
}
