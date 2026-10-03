/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** Bean Validation constraints of the request bodies; controllers apply them through {@code @Valid}. */
class RequestValidationTest {

    private static ValidatorFactory validatorFactory;
    private static Validator validator;

    @BeforeAll
    static void createValidator() {
        validatorFactory = Validation.buildDefaultValidatorFactory();
        validator = validatorFactory.getValidator();
    }

    @AfterAll
    static void closeValidatorFactory() {
        validatorFactory.close();
    }

    @Test
    void receiveStock_acceptsValidRequest() {
        assertThat(violatedProperties(new ReceiveStockRequest("BER1", 20, "PO-1"))).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(longs = {0, -1})
    void receiveStock_rejectsNonPositiveQuantity(long quantity) {
        assertThat(violatedProperties(new ReceiveStockRequest("BER1", quantity, "PO-1")))
                .containsExactly("quantity");
    }

    @Test
    void receiveStock_rejectsBlankWarehouseCodeAndReference() {
        assertThat(violatedProperties(new ReceiveStockRequest(" ", 20, "")))
                .containsExactlyInAnyOrder("warehouseCode", "reference");
    }

    @Test
    void receiveStock_limitsWarehouseCodeTo16Characters() {
        assertThat(violatedProperties(new ReceiveStockRequest("W".repeat(16), 20, "PO-1"))).isEmpty();
        assertThat(violatedProperties(new ReceiveStockRequest("W".repeat(17), 20, "PO-1")))
                .containsExactly("warehouseCode");
    }

    @Test
    void adjustStock_acceptsNegativeDelta() {
        assertThat(violatedProperties(new AdjustStockRequest("BER1", -3, "damaged"))).isEmpty();
    }

    @Test
    void adjustStock_rejectsMissingWarehouseCode() {
        assertThat(violatedProperties(new AdjustStockRequest(null, -3, "damaged")))
                .containsExactly("warehouseCode");
    }

    @Test
    void adjustStock_limitsReasonTo128Characters() {
        assertThat(violatedProperties(new AdjustStockRequest("BER1", -3, "x".repeat(128)))).isEmpty();
        assertThat(violatedProperties(new AdjustStockRequest("BER1", -3, "x".repeat(129))))
                .containsExactly("reason");
    }

    @Test
    void createReservation_acceptsValidRequest() {
        assertThat(violatedProperties(new CreateReservationRequest(10L, "BER1", 2, "SO-1"))).isEmpty();
    }

    @Test
    void createReservation_rejectsNonPositiveProductIdAndQuantity() {
        assertThat(violatedProperties(new CreateReservationRequest(0L, "BER1", 0, "SO-1")))
                .containsExactlyInAnyOrder("productId", "quantity");
    }

    @Test
    void createReservation_limitsOrderReferenceTo64Characters() {
        assertThat(violatedProperties(new CreateReservationRequest(10L, "BER1", 2, "S".repeat(65))))
                .containsExactly("orderReference");
    }

    @Test
    void createProduct_acceptsRequestWithoutDescription() {
        assertThat(violatedProperties(new CreateProductRequest("SKU-1", "Blue mug", null))).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "sku-1", "SKU 1", "SKU_1"})
    void createProduct_rejectsSkuOutsideUppercaseDigitsAndDashes(String sku) {
        assertThat(violatedProperties(new CreateProductRequest(sku, "Blue mug", null)))
                .containsExactly("sku");
    }

    @Test
    void createProduct_limitsNameAndDescriptionLength() {
        assertThat(violatedProperties(new CreateProductRequest("SKU-1", "n".repeat(256), "d".repeat(2001))))
                .containsExactlyInAnyOrder("name", "description");
    }

    private static Set<String> violatedProperties(Object request) {
        return validator.validate(request).stream()
                .map(violation -> violation.getPropertyPath().toString())
                .collect(Collectors.toSet());
    }
}
