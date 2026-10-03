/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.service;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.reservation;
import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.common.ReservationStateException;
import com.acme.inventory.config.InventoryProperties;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.Reservation;
import com.acme.inventory.domain.ReservationStatus;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.repository.ProductRepository;
import com.acme.inventory.repository.ReservationRepository;
import java.time.Clock;
import java.time.Duration;
import java.time.ZoneOffset;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ReservationServiceTest {

    @Mock
    private ReservationRepository reservations;

    @Mock
    private ProductRepository products;

    @Mock
    private StockLedger ledger;

    private ReservationService reservationService;

    @BeforeEach
    void setUp() {
        InventoryProperties properties = new InventoryProperties(Duration.ofMinutes(30), 100, Duration.ofMinutes(1));
        reservationService = new ReservationService(reservations, products, ledger, properties,
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void reserve_locksLevelRecordsMovementAndSetsExpiry() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);
        when(products.existsById(10L)).thenReturn(true);
        when(ledger.lock(10L, "BER1")).thenReturn(level);
        when(reservations.save(any(Reservation.class))).thenAnswer(invocation -> invocation.getArgument(0));

        Reservation reservation = reservationService.reserve(10L, "BER1", 3, "SO-1");

        verify(ledger).record(level, MovementType.RESERVE, 3, "order:SO-1");
        assertThat(reservation.getExpiresAt()).isEqualTo(NOW.plus(Duration.ofMinutes(30)));
        assertThat(reservation.getStatus()).isEqualTo(ReservationStatus.ACTIVE);
    }

    @Test
    void release_releasesReservedQuantity() {
        Reservation reservation = reservation(7L, 10L, "BER1", 3);
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 3);
        when(reservations.findById(7L)).thenReturn(Optional.of(reservation));
        when(ledger.lock(10L, "BER1")).thenReturn(level);

        reservationService.release(7L);

        assertThat(reservation.getStatus()).isEqualTo(ReservationStatus.RELEASED);
        verify(ledger).record(level, MovementType.RELEASE, 3, "reservation:7");
    }

    @Test
    void release_rejectsReservationThatIsNoLongerActive() {
        Reservation reservation = reservation(7L, 10L, "BER1", 3);
        reservation.fulfill(NOW);
        when(reservations.findById(7L)).thenReturn(Optional.of(reservation));

        assertThatThrownBy(() -> reservationService.release(7L)).isInstanceOf(ReservationStateException.class);
        verify(ledger, never()).record(any(), any(), anyLong(), anyString());
    }

    @Test
    void fulfill_consumesReservedStock() {
        Reservation reservation = reservation(7L, 10L, "BER1", 3);
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 3);
        when(reservations.findById(7L)).thenReturn(Optional.of(reservation));
        when(ledger.lock(10L, "BER1")).thenReturn(level);

        reservationService.fulfill(7L);

        assertThat(reservation.getStatus()).isEqualTo(ReservationStatus.FULFILLED);
        verify(ledger).record(level, MovementType.FULFILL, 3, "reservation:7");
    }
}
