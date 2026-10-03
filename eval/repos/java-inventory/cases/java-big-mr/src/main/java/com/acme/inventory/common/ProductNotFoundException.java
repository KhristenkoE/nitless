/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

public class ProductNotFoundException extends InventoryException {

    public ProductNotFoundException(long productId) {
        super(ErrorCode.PRODUCT_NOT_FOUND, "Product " + productId + " not found");
    }
}
