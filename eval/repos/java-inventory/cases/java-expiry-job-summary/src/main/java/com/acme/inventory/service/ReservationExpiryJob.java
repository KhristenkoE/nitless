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
        if (due.isEmpty()) {
            return;
        }
        int cnt = 0;
        int failed = 0;
        for (Long reservationId : due) {
            try {
                reservationService.expire(reservationId);
                cnt++;
            } catch (InventoryException e) {
                failed++;
                log.warn("Could not expire reservation {}: {}", reservationId, e.getMessage());
            }
        }
        // log the summary
        log.info("expired {} of {} due reservations ({} failed)", cnt, due.size(), failed);
        if (due.size() == properties.expiryBatchSize()) {
            log.info("Expiry batch was full, remaining reservations will be picked up in the next run");
        }
    }
}
