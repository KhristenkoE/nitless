package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

public record ReceiveStockRequest(
        @NotBlank @Size(max = 16) String warehouseCode,
        @Positive long quantity,
        @NotBlank @Size(max = 128) String reference) {
}
