package com.acme.inventory.service;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.common.ReservationStateException;
import com.acme.inventory.config.InventoryProperties;
import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ReservationExpiryJobTest {

    @Mock
    private ReservationService reservationService;

    private ReservationExpiryJob job;

    @BeforeEach
    void setUp() {
        InventoryProperties properties = new InventoryProperties(Duration.ofMinutes(30), 50, Duration.ofMinutes(1));
        job = new ReservationExpiryJob(reservationService, properties);
    }

    @Test
    void expiresEveryDueReservation() {
        when(reservationService.findExpiredIds(50)).thenReturn(List.of(1L, 2L));

        job.expireDueReservations();

        verify(reservationService).expire(1L);
        verify(reservationService).expire(2L);
    }

    @Test
    void continuesWhenOneReservationWasAlreadyClosed() {
        when(reservationService.findExpiredIds(50)).thenReturn(List.of(1L, 2L));
        doThrow(new ReservationStateException(1L, "RELEASED", "expired")).when(reservationService).expire(1L);

        job.expireDueReservations();

        verify(reservationService).expire(2L);
    }

    @Test
    void doesNothingWhenNoReservationIsDue() {
        when(reservationService.findExpiredIds(50)).thenReturn(List.of());

        job.expireDueReservations();

        verify(reservationService, never()).expire(anyLong());
    }
}
