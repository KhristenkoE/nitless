/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record CreateProductRequest(
        @NotBlank @Size(max = 64) @Pattern(regexp = "[A-Z0-9-]+") String sku,
        @NotBlank @Size(max = 255) String name,
        @Size(max = 2000) String description) {
}
