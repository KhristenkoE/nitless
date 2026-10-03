package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** Manual correction; {@code delta} is negative for write-offs. */
public record AdjustStockRequest(
        @NotBlank @Size(max = 16) String warehouseCode,
        long delta,
        @NotBlank @Size(max = 128) String reason) {
}
