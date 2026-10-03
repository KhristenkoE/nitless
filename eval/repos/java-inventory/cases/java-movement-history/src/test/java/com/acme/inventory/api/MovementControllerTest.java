package com.acme.inventory.api;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.stockLevel;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.domain.StockMovement;
import com.acme.inventory.service.MovementHistoryService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(MovementController.class)
class MovementControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private MovementHistoryService movementHistoryService;

    @Test
    void history_returnsNewestMovementsFirst() throws Exception {
        StockLevel level = stockLevel(1L, 10L, "BER1", 18, 2);
        StockMovement movement = new StockMovement(level, MovementType.RESERVE, 2, "order:SO-1", NOW);
        ReflectionTestUtils.setField(movement, "id", 31L);
        PageRequest expected = PageRequest.of(0, 50, Sort.by(Sort.Direction.DESC, "occurredAt", "id"));
        when(movementHistoryService.history(eq(10L), isNull(), eq(expected)))
                .thenReturn(new PageImpl<>(List.of(movement), expected, 1));

        mockMvc.perform(get("/api/v1/products/10/movements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].id").value(31))
                .andExpect(jsonPath("$.items[0].type").value("RESERVE"))
                .andExpect(jsonPath("$.items[0].onHandAfter").value(18))
                .andExpect(jsonPath("$.items[0].reservedAfter").value(2))
                .andExpect(jsonPath("$.items[0].reference").value("order:SO-1"))
                .andExpect(jsonPath("$.totalElements").value(1));
    }

    @Test
    void history_filtersByWarehouse() throws Exception {
        when(movementHistoryService.history(eq(10L), eq("HAM2"), any()))
                .thenReturn(new PageImpl<>(List.of()));

        mockMvc.perform(get("/api/v1/products/10/movements").param("warehouse", "HAM2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items").isEmpty());
    }

    @Test
    void history_capsPageSize() throws Exception {
        PageRequest capped = PageRequest.of(0, 200, Sort.by(Sort.Direction.DESC, "occurredAt", "id"));
        when(movementHistoryService.history(eq(10L), isNull(), eq(capped)))
                .thenReturn(new PageImpl<>(List.of(), capped, 0));

        mockMvc.perform(get("/api/v1/products/10/movements").param("size", "1000"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.size").value(200));
    }
}
