package com.acme.inventory.api.dto;

import com.acme.inventory.domain.Product;
import java.time.Instant;

public record ProductResponse(
        long id,
        String sku,
        String name,
        String description,
        String status,
        Instant createdAt,
        Instant updatedAt) {

    public static ProductResponse from(Product product) {
        return new ProductResponse(product.getId(), product.getSku(), product.getName(), product.getDescription(),
                product.getStatus().name(), product.getCreatedAt(), product.getUpdatedAt());
    }
}
