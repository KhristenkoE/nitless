package com.acme.inventory.service;

import com.acme.inventory.common.InventoryException;
import com.acme.inventory.config.InventoryProperties;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Releases the stock held by reservations whose TTL has passed. Each reservation is expired in
 * its own transaction so a slow batch never holds stock level locks for long.
 */
@Component
public class ReservationExpiryJob {

    private static final Logger log = LoggerFactory.getLogger(ReservationExpiryJob.class);

    private final ReservationService reservationService;
    private final InventoryProperties properties;

    public ReservationExpiryJob(ReservationService reservationService, InventoryProperties properties) {
        this.reservationService = reservationService;
        this.properties = properties;
    }

    @Scheduled(fixedDelayString = "${inventory.expiry-interval}")
    public void expireDueReservations() {
        List<Long> due = reservationService.findExpiredIds(properties.expiryBatchSize());
        for (Long reservationId : due) {
            try {
                reservationService.expire(reservationId);
            } catch (InventoryException e) {
                log.warn("Could not expire reservation {}: {}", reservationId, e.getMessage());
            }
        }
    }
}
