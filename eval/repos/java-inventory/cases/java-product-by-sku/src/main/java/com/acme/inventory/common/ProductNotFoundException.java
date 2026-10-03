package com.acme.inventory.common;

public class ProductNotFoundException extends InventoryException {

    public ProductNotFoundException(long productId) {
        super(ErrorCode.PRODUCT_NOT_FOUND, "Product " + productId + " not found");
    }

    public ProductNotFoundException(String sku) {
        super(ErrorCode.PRODUCT_NOT_FOUND, "Product with SKU " + sku + " not found");
    }
}
