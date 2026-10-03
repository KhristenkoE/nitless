package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;

/** Result of a physical count of one product in one warehouse. */
public record CycleCountRequest(
        @NotBlank @Size(max = 16) String warehouseCode,
        @NotNull @PositiveOrZero Long countedQuantity,
        @NotBlank @Size(max = 64) String countId) {
}
