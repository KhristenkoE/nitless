/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import com.acme.inventory.api.dto.ErrorResponse;
import com.acme.inventory.common.InsufficientStockException;
import com.acme.inventory.common.StockLevelNotFoundException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.validation.MapBindingResult;
import org.springframework.web.bind.MethodArgumentNotValidException;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    void handleInventoryException_mapsNotFoundErrorTo404() {
        ResponseEntity<ErrorResponse> response =
                handler.handleInventoryException(new StockLevelNotFoundException(10L, "BER1"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody())
                .isEqualTo(new ErrorResponse("STOCK_LEVEL_NOT_FOUND", "No stock of product 10 in warehouse BER1"));
    }

    @Test
    void handleInventoryException_mapsInsufficientStockTo409() {
        ResponseEntity<ErrorResponse> response =
                handler.handleInventoryException(new InsufficientStockException(10L, "BER1", 2, 5));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(response.getBody()).isEqualTo(new ErrorResponse("INSUFFICIENT_STOCK",
                "Insufficient stock of product 10 in BER1: available 2, requested 5"));
    }

    @Test
    void handleValidation_reportsFieldError() {
        BindingResult bindingResult = new MapBindingResult(Map.of(), "receiveStockRequest");
        bindingResult.addError(new FieldError("receiveStockRequest", "quantity", "must be greater than 0"));

        ResponseEntity<ErrorResponse> response = handler.handleValidation(invalidArgument(bindingResult));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody())
                .isEqualTo(new ErrorResponse("INVALID_REQUEST", "quantity: must be greater than 0"));
    }

    @Test
    void handleValidation_joinsFieldErrorsInReportedOrder() {
        BindingResult bindingResult = new MapBindingResult(Map.of(), "receiveStockRequest");
        bindingResult.addError(new FieldError("receiveStockRequest", "warehouseCode", "must not be blank"));
        bindingResult.addError(new FieldError("receiveStockRequest", "quantity", "must be greater than 0"));

        ResponseEntity<ErrorResponse> response = handler.handleValidation(invalidArgument(bindingResult));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isEqualTo(new ErrorResponse("INVALID_REQUEST",
                "warehouseCode: must not be blank; quantity: must be greater than 0"));
    }

    private static MethodArgumentNotValidException invalidArgument(BindingResult bindingResult) {
        return new MethodArgumentNotValidException(mock(MethodParameter.class), bindingResult);
    }
}
