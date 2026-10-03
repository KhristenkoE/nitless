package com.acme.inventory.api;

import com.acme.inventory.api.dto.CreateReservationRequest;
import com.acme.inventory.api.dto.ReservationResponse;
import com.acme.inventory.domain.Reservation;
import com.acme.inventory.service.ReservationService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/reservations")
public class ReservationController {

    private final ReservationService reservationService;

    public ReservationController(ReservationService reservationService) {
        this.reservationService = reservationService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ReservationResponse reserve(@Valid @RequestBody CreateReservationRequest request) {
        return ReservationResponse.from(reservationService.reserve(request.productId(), request.warehouseCode(),
                request.quantity(), request.orderReference()));
    }

    @GetMapping
    public List<Reservation> findByOrder(@RequestParam String orderReference) {
        return reservationService.findByOrder(orderReference);
    }

    @GetMapping("/{reservationId}")
    public ReservationResponse get(@PathVariable long reservationId) {
        return ReservationResponse.from(reservationService.get(reservationId));
    }

    @PostMapping("/{reservationId}/release")
    public ReservationResponse release(@PathVariable long reservationId) {
        return ReservationResponse.from(reservationService.release(reservationId));
    }

    @PostMapping("/{reservationId}/fulfill")
    public ReservationResponse fulfill(@PathVariable long reservationId) {
        return ReservationResponse.from(reservationService.fulfill(reservationId));
    }
}
