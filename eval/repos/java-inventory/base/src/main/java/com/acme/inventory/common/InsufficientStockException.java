package com.acme.inventory.common;

public class InsufficientStockException extends InventoryException {

    public InsufficientStockException(long productId, String warehouseCode, long available, long requested) {
        super(ErrorCode.INSUFFICIENT_STOCK,
                "Insufficient stock of product %d in %s: available %d, requested %d"
                        .formatted(productId, warehouseCode, available, requested));
    }
}
