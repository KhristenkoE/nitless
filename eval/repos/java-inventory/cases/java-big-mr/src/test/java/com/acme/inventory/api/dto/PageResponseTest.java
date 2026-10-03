/*
 * Copyright (c) 2026 Acme Commerce GmbH
 * SPDX-License-Identifier: Apache-2.0
 */
package com.acme.inventory.api.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;

class PageResponseTest {

    @Test
    void from_mapsItemsAndCopiesPaging() {
        PageImpl<Long> page = new PageImpl<>(List.of(3L, 4L), PageRequest.of(1, 2), 5);

        PageResponse<String> response = PageResponse.from(page, id -> "SKU-" + id);

        assertThat(response.items()).containsExactly("SKU-3", "SKU-4");
        assertThat(response.page()).isEqualTo(1);
        assertThat(response.size()).isEqualTo(2);
        assertThat(response.totalElements()).isEqualTo(5);
        assertThat(response.totalPages()).isEqualTo(3);
    }

    @Test
    void from_returnsEmptyResponseForEmptyPage() {
        PageImpl<Long> page = new PageImpl<>(List.of(), PageRequest.of(0, 20), 0);

        PageResponse<String> response = PageResponse.from(page, id -> "SKU-" + id);

        assertThat(response.items()).isEmpty();
        assertThat(response.page()).isZero();
        assertThat(response.size()).isEqualTo(20);
        assertThat(response.totalElements()).isZero();
        assertThat(response.totalPages()).isZero();
    }
}
