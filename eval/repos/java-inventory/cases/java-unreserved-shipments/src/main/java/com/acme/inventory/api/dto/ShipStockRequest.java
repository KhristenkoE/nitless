package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

/** Goods shipped outside the reservation flow; {@code reference} is the delivery note number. */
public record ShipStockRequest(
        @NotBlank @Size(max = 16) String warehouseCode,
        @Positive long quantity,
        @NotBlank @Size(max = 128) String reference) {
}
