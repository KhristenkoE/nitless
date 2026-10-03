package com.acme.inventory.common;

public class StockLevelNotFoundException extends InventoryException {

    public StockLevelNotFoundException(long productId, String warehouseCode) {
        super(ErrorCode.STOCK_LEVEL_NOT_FOUND,
                "No stock of product " + productId + " in warehouse " + warehouseCode);
    }
}
