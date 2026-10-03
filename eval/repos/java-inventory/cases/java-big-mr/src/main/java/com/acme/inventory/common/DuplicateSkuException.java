/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

public class DuplicateSkuException extends InventoryException {

    public DuplicateSkuException(String sku) {
        super(ErrorCode.DUPLICATE_SKU, "A product with SKU " + sku + " already exists");
    }
}
