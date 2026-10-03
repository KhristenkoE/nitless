package com.acme.inventory.config;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "inventory")
public record InventoryProperties(
        @NotNull Duration reservationTtl,
        @Positive int expiryBatchSize,
        @NotNull Duration expiryInterval) {
}
