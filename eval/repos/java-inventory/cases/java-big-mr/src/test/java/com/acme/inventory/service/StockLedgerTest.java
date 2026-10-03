/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.service;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.common.InsufficientStockException;
import com.acme.inventory.common.InvalidRequestException;
import com.acme.inventory.common.StockLevelNotFoundException;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.domain.StockMovement;
import com.acme.inventory.repository.StockLevelRepository;
import com.acme.inventory.repository.StockMovementRepository;
import java.time.Clock;
import java.time.ZoneOffset;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class StockLedgerTest {

    @Mock
    private StockLevelRepository stockLevels;

    @Mock
    private StockMovementRepository movements;

    private StockLedger ledger;

    @BeforeEach
    void setUp() {
        ledger = new StockLedger(stockLevels, movements, Clock.fixed(NOW, ZoneOffset.UTC));
        lenient().when(movements.save(any(StockMovement.class))).thenAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void record_receiptIncreasesOnHand() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 5, 2);

        StockMovement movement = ledger.record(level, MovementType.RECEIPT, 20, "PO-1");

        assertThat(level.getQuantity()).isEqualTo(25);
        assertThat(level.getReserved()).isEqualTo(2);
        assertThat(movement.getOnHandAfter()).isEqualTo(25);
        assertThat(movement.getOccurredAt()).isEqualTo(NOW);
    }

    @Test
    void record_reserveIncreasesReservedOnly() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);

        ledger.record(level, MovementType.RESERVE, 4, "order:SO-1");

        assertThat(level.getQuantity()).isEqualTo(10);
        assertThat(level.getReserved()).isEqualTo(4);
        assertThat(level.getAvailable()).isEqualTo(6);
    }

    @Test
    void record_fulfillDecreasesOnHandAndReserved() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 4);

        ledger.record(level, MovementType.FULFILL, 4, "reservation:7");

        assertThat(level.getQuantity()).isEqualTo(6);
        assertThat(level.getReserved()).isZero();
    }

    @Test
    void record_negativeAdjustmentDecreasesOnHand() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);

        ledger.record(level, MovementType.ADJUSTMENT, -3, "damaged");

        assertThat(level.getQuantity()).isEqualTo(7);
    }

    @Test
    void record_rejectsMovementThatWouldConsumeReservedStock() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 8);

        assertThatThrownBy(() -> ledger.record(level, MovementType.RESERVE, 3, "order:SO-2"))
                .isInstanceOf(InsufficientStockException.class);
        assertThat(level.getReserved()).isEqualTo(8);
        verify(movements, never()).save(any());
    }

    @Test
    void record_rejectsZeroQuantity() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);

        assertThatThrownBy(() -> ledger.record(level, MovementType.ADJUSTMENT, 0, "noop"))
                .isInstanceOf(InvalidRequestException.class);
    }

    @Test
    void lock_throwsWhenStockLevelDoesNotExist() {
        when(stockLevels.findForUpdate(10L, "BER1")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> ledger.lock(10L, "BER1")).isInstanceOf(StockLevelNotFoundException.class);
    }
}
