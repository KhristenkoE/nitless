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
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.common.InsufficientStockException;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.domain.StockMovement;
import com.acme.inventory.repository.StockLevelRepository;
import com.acme.inventory.repository.StockMovementRepository;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class StockLedgerMovementTest {

    /** Clock time of the ledger; later than the fixtures' {@code NOW} so written timestamps stand out. */
    private static final Instant LATER = NOW.plus(Duration.ofMinutes(5));

    @Mock
    private StockLevelRepository stockLevels;

    @Mock
    private StockMovementRepository movements;

    private StockLedger ledger;

    @BeforeEach
    void setUp() {
        ledger = new StockLedger(stockLevels, movements, Clock.fixed(LATER, ZoneOffset.UTC));
    }

    @Test
    void lockOrCreate_returnsExistingStockLevelWithoutInserting() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 2);
        when(stockLevels.findForUpdate(10L, "BER1")).thenReturn(Optional.of(level));

        StockLevel result = ledger.lockOrCreate(10L, "BER1");

        assertThat(result).isSameAs(level);
        verify(stockLevels, never()).saveAndFlush(any());
    }

    @Test
    void lockOrCreate_insertsEmptyStockLevelWhenNoneExists() {
        when(stockLevels.findForUpdate(10L, "HAM2")).thenReturn(Optional.empty());
        when(stockLevels.saveAndFlush(any(StockLevel.class))).thenAnswer(invocation -> invocation.getArgument(0));

        StockLevel result = ledger.lockOrCreate(10L, "HAM2");

        assertThat(result.getProductId()).isEqualTo(10L);
        assertThat(result.getWarehouseCode()).isEqualTo("HAM2");
        assertThat(result.getQuantity()).isZero();
        assertThat(result.getReserved()).isZero();
        assertThat(result.getUpdatedAt()).isEqualTo(LATER);
    }

    @Test
    void record_savesSnapshotOfLevelAfterTheMovement() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 2);
        when(movements.save(any(StockMovement.class))).thenAnswer(invocation -> invocation.getArgument(0));

        StockMovement movement = ledger.record(level, MovementType.RESERVE, 3, "order:SO-1");

        assertThat(movement.getStockLevelId()).isEqualTo(1L);
        assertThat(movement.getProductId()).isEqualTo(10L);
        assertThat(movement.getWarehouseCode()).isEqualTo("BER1");
        assertThat(movement.getType()).isEqualTo(MovementType.RESERVE);
        assertThat(movement.getQuantity()).isEqualTo(3);
        assertThat(movement.getOnHandAfter()).isEqualTo(10);
        assertThat(movement.getReservedAfter()).isEqualTo(5);
        assertThat(movement.getReference()).isEqualTo("order:SO-1");
        assertThat(movement.getOccurredAt()).isEqualTo(LATER);
        assertThat(level.getUpdatedAt()).isEqualTo(LATER);
    }

    @Test
    void record_shipmentDecreasesOnHandOnly() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);
        when(movements.save(any(StockMovement.class))).thenAnswer(invocation -> invocation.getArgument(0));

        ledger.record(level, MovementType.SHIPMENT, 4, "shipment:SH-1");

        assertThat(level.getQuantity()).isEqualTo(6);
        assertThat(level.getReserved()).isZero();
    }

    @Test
    void record_releaseDecreasesReservedOnly() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 4);
        when(movements.save(any(StockMovement.class))).thenAnswer(invocation -> invocation.getArgument(0));

        ledger.record(level, MovementType.RELEASE, 4, "reservation:7");

        assertThat(level.getQuantity()).isEqualTo(10);
        assertThat(level.getReserved()).isZero();
        assertThat(level.getAvailable()).isEqualTo(10);
    }

    @Test
    void record_allowsReservingAllAvailableStock() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 4);
        when(movements.save(any(StockMovement.class))).thenAnswer(invocation -> invocation.getArgument(0));

        ledger.record(level, MovementType.RESERVE, 6, "order:SO-2");

        assertThat(level.getReserved()).isEqualTo(10);
        assertThat(level.getAvailable()).isZero();
    }

    @Test
    void record_keepsSignOfAdjustmentQuantityInHistory() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);
        when(movements.save(any(StockMovement.class))).thenAnswer(invocation -> invocation.getArgument(0));

        StockMovement movement = ledger.record(level, MovementType.ADJUSTMENT, -3, "damaged");

        assertThat(movement.getQuantity()).isEqualTo(-3);
        assertThat(movement.getOnHandAfter()).isEqualTo(7);
    }

    @Test
    void record_rejectsShipmentThatWouldConsumeReservedStock() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 8);

        assertThatThrownBy(() -> ledger.record(level, MovementType.SHIPMENT, 3, "shipment:SH-2"))
                .isInstanceOf(InsufficientStockException.class)
                .hasMessage("Insufficient stock of product 10 in BER1: available 2, requested 3");
        assertThat(level.getQuantity()).isEqualTo(10);
        assertThat(level.getUpdatedAt()).isEqualTo(NOW);
        verify(movements, never()).save(any());
    }

    @Test
    void record_rejectsReleasingMoreThanIsReserved() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 2);

        assertThatThrownBy(() -> ledger.record(level, MovementType.RELEASE, 3, "reservation:8"))
                .isInstanceOf(InsufficientStockException.class)
                .hasMessage("Insufficient stock of product 10 in BER1: available 8, requested 3");
        assertThat(level.getReserved()).isEqualTo(2);
        verify(movements, never()).save(any());
    }

    @Test
    void record_reportsAbsoluteQuantityOfRejectedNegativeAdjustment() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 8);

        assertThatThrownBy(() -> ledger.record(level, MovementType.ADJUSTMENT, -5, "stocktake"))
                .isInstanceOf(InsufficientStockException.class)
                .hasMessage("Insufficient stock of product 10 in BER1: available 2, requested 5");
        assertThat(level.getQuantity()).isEqualTo(10);
        verify(movements, never()).save(any());
    }
}
