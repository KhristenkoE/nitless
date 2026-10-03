package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

public record TransferStockRequest(
        @NotBlank @Size(max = 16) String fromWarehouse,
        @NotBlank @Size(max = 16) String toWarehouse,
        @Positive long quantity,
        @NotBlank @Size(max = 100) String reference) {
}
