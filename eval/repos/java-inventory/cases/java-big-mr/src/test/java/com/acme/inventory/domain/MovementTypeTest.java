/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.domain;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class MovementTypeTest {

    @ParameterizedTest
    @CsvSource({
        "RECEIPT, 1, 0",
        "SHIPMENT, -1, 0",
        "ADJUSTMENT, 1, 0",
        "RESERVE, 0, 1",
        "RELEASE, 0, -1",
        "FULFILL, -1, -1"
    })
    void signs_describeEffectOnOnHandAndReserved(MovementType type, int onHandSign, int reservedSign) {
        assertThat(type.onHandSign()).isEqualTo(onHandSign);
        assertThat(type.reservedSign()).isEqualTo(reservedSign);
    }
}
