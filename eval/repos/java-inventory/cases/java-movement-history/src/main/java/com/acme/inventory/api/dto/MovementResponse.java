package com.acme.inventory.api.dto;

import com.acme.inventory.domain.StockMovement;
import java.time.Instant;

public record MovementResponse(
        long id,
        String warehouseCode,
        String type,
        long quantity,
        long onHandAfter,
        long reservedAfter,
        String reference,
        Instant occurredAt) {

    public static MovementResponse from(StockMovement movement) {
        return new MovementResponse(movement.getId(), movement.getWarehouseCode(), movement.getType().name(),
                movement.getQuantity(), movement.getOnHandAfter(), movement.getReservedAfter(),
                movement.getReference(), movement.getOccurredAt());
    }
}
