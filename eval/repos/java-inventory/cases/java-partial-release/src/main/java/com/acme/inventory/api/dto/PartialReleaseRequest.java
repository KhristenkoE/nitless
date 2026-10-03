package com.acme.inventory.api.dto;

import jakarta.validation.constraints.Positive;

public record PartialReleaseRequest(@Positive long quantity) {
}
