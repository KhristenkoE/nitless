package com.acme.inventory.common;

public class InvalidRequestException extends InventoryException {

    public InvalidRequestException(String message) {
        super(ErrorCode.INVALID_REQUEST, message);
    }
}
