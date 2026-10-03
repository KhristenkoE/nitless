/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

/**
 * Base class for all domain errors. {@code GlobalExceptionHandler} turns the {@link ErrorCode}
 * into the HTTP status and the {@code code} field of the error body.
 */
public abstract class InventoryException extends RuntimeException {

    private final ErrorCode errorCode;

    protected InventoryException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
