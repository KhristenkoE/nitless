package com.acme.inventory.api;

import static com.acme.inventory.TestData.reservation;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.acme.inventory.TestData;
import com.acme.inventory.common.InsufficientStockException;
import com.acme.inventory.common.InvalidRequestException;
import com.acme.inventory.common.ReservationNotFoundException;
import com.acme.inventory.common.ReservationStateException;
import com.acme.inventory.domain.Reservation;
import com.acme.inventory.service.ReservationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(ReservationController.class)
class ReservationControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private ReservationService reservationService;

    @Test
    void reserve_returns201() throws Exception {
        when(reservationService.reserve(10L, "BER1", 2, "SO-1")).thenReturn(reservation(7L, 10L, "BER1", 2));

        mockMvc.perform(post("/api/v1/reservations")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"productId": 10, "warehouseCode": "BER1", "quantity": 2, "orderReference": "SO-1"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(7))
                .andExpect(jsonPath("$.status").value("ACTIVE"));
    }

    @Test
    void reserve_returns409WhenNotEnoughStock() throws Exception {
        when(reservationService.reserve(10L, "BER1", 20, "SO-1"))
                .thenThrow(new InsufficientStockException(10L, "BER1", 5, 20));

        mockMvc.perform(post("/api/v1/reservations")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"productId": 10, "warehouseCode": "BER1", "quantity": 20, "orderReference": "SO-1"}
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"));
    }

    @Test
    void get_returns404WhenMissing() throws Exception {
        when(reservationService.get(8L)).thenThrow(new ReservationNotFoundException(8L));

        mockMvc.perform(get("/api/v1/reservations/8"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("RESERVATION_NOT_FOUND"));
    }

    @Test
    void release_returns409WhenAlreadyFulfilled() throws Exception {
        when(reservationService.release(7L)).thenThrow(new ReservationStateException(7L, "FULFILLED", "released"));

        mockMvc.perform(post("/api/v1/reservations/7/release"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INVALID_RESERVATION_STATE"));
    }

    @Test
    void releasePartially_returnsRemainingQuantity() throws Exception {
        Reservation reservation = reservation(7L, 10L, "BER1", 5);
        reservation.releasePartially(2, TestData.NOW);
        when(reservationService.releasePartially(7L, 2)).thenReturn(reservation);

        mockMvc.perform(post("/api/v1/reservations/7/partial-release")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"quantity": 2}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.quantity").value(3))
                .andExpect(jsonPath("$.status").value("ACTIVE"));
    }

    @Test
    void releasePartially_returns400WhenReleasingEverything() throws Exception {
        when(reservationService.releasePartially(7L, 5))
                .thenThrow(new InvalidRequestException("Cannot partially release 5 of 5 reserved units"));

        mockMvc.perform(post("/api/v1/reservations/7/partial-release")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"quantity": 5}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }
}
