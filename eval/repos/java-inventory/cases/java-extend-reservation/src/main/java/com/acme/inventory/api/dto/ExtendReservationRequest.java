package com.acme.inventory.api.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

/** Extends a reservation by up to two hours at a time. */
public record ExtendReservationRequest(@Min(1) @Max(120) int minutes) {
}
