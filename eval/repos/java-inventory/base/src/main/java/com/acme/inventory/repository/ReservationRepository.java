package com.acme.inventory.repository;

import com.acme.inventory.domain.Reservation;
import com.acme.inventory.domain.ReservationStatus;
import java.time.Instant;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ReservationRepository extends JpaRepository<Reservation, Long> {

    List<Reservation> findByStatusAndExpiresAtBeforeOrderByExpiresAt(ReservationStatus status, Instant cutoff,
                                                                     Pageable pageable);

    List<Reservation> findByOrderReference(String orderReference);
}
