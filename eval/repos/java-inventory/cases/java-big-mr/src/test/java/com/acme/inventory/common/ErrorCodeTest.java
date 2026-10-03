/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.common;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.http.HttpStatus;

class ErrorCodeTest {

    @ParameterizedTest
    @CsvSource({
        "PRODUCT_NOT_FOUND, NOT_FOUND",
        "DUPLICATE_SKU, CONFLICT",
        "STOCK_LEVEL_NOT_FOUND, NOT_FOUND",
        "INSUFFICIENT_STOCK, CONFLICT",
        "RESERVATION_NOT_FOUND, NOT_FOUND",
        "INVALID_RESERVATION_STATE, CONFLICT",
        "INVALID_REQUEST, BAD_REQUEST"
    })
    void status_mapsEachCodeToItsHttpStatus(ErrorCode code, HttpStatus expected) {
        assertThat(code.status()).isEqualTo(expected);
    }
}
