package com.acme.inventory.service;

import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.common.ReservationNotFoundException;
import com.acme.inventory.config.InventoryProperties;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.Reservation;
import com.acme.inventory.domain.ReservationStatus;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.repository.ProductRepository;
import com.acme.inventory.repository.ReservationRepository;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ReservationService {

    private final ReservationRepository reservations;
    private final ProductRepository products;
    private final StockLedger ledger;
    private final InventoryProperties properties;
    private final Clock clock;

    public ReservationService(ReservationRepository reservations, ProductRepository products, StockLedger ledger,
                              InventoryProperties properties, Clock clock) {
        this.reservations = reservations;
        this.products = products;
        this.ledger = ledger;
        this.properties = properties;
        this.clock = clock;
    }

    @Transactional
    public Reservation reserve(long productId, String warehouseCode, long quantity, String orderReference) {
        if (!products.existsById(productId)) {
            throw new ProductNotFoundException(productId);
        }
        StockLevel level = ledger.lock(productId, warehouseCode);
        ledger.record(level, MovementType.RESERVE, quantity, "order:" + orderReference);
        Instant now = clock.instant();
        Reservation reservation = new Reservation(productId, warehouseCode, quantity, orderReference,
                now, now.plus(properties.reservationTtl()));
        return reservations.save(reservation);
    }

    @Transactional(readOnly = true)
    public Reservation get(long reservationId) {
        return find(reservationId);
    }

    @Transactional
    public Reservation release(long reservationId) {
        Reservation reservation = find(reservationId);
        StockLevel level = ledger.lock(reservation.getProductId(), reservation.getWarehouseCode());
        reservation.release(clock.instant());
        ledger.record(level, MovementType.RELEASE, reservation.getQuantity(), "reservation:" + reservationId);
        return reservation;
    }

    @Transactional
    public Reservation fulfill(long reservationId) {
        Reservation reservation = find(reservationId);
        StockLevel level = ledger.lock(reservation.getProductId(), reservation.getWarehouseCode());
        reservation.fulfill(clock.instant());
        ledger.record(level, MovementType.FULFILL, reservation.getQuantity(), "reservation:" + reservationId);
        return reservation;
    }

    /**
     * Pushes back the expiry of an active reservation, e.g. while the payment provider retries a
     * charge. Overdue reservations that the expiry job has not picked up yet are extended from now.
     */
    @Transactional
    public Reservation extend(long reservationId, Duration extension) {
        Reservation reservation = find(reservationId);
        ledger.lock(reservation.getProductId(), reservation.getWarehouseCode());
        if (!reservation.isActive()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "Reservation " + reservationId + " is " + reservation.getStatus() + " and cannot be extended");
        }
        Instant now = clock.instant();
        Instant from = reservation.getExpiresAt().isAfter(now) ? reservation.getExpiresAt() : now;
        reservation.extendUntil(from.plus(extension), now);
        return reservation;
    }

    @Transactional(readOnly = true)
    public List<Long> findExpiredIds(int limit) {
        return reservations.findByStatusAndExpiresAtBeforeOrderByExpiresAt(
                        ReservationStatus.ACTIVE, clock.instant(), PageRequest.of(0, limit))
                .stream()
                .map(Reservation::getId)
                .toList();
    }

    @Transactional
    public void expire(long reservationId) {
        Reservation reservation = find(reservationId);
        StockLevel level = ledger.lock(reservation.getProductId(), reservation.getWarehouseCode());
        reservation.expire(clock.instant());
        ledger.record(level, MovementType.RELEASE, reservation.getQuantity(), "expiry:" + reservationId);
    }

    private Reservation find(long reservationId) {
        return reservations.findById(reservationId)
                .orElseThrow(() -> new ReservationNotFoundException(reservationId));
    }
}
