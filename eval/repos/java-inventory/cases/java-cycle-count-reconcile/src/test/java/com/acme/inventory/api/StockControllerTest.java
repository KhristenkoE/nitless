package com.acme.inventory.api;

import static com.acme.inventory.TestData.stockLevel;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.acme.inventory.common.InsufficientStockException;
import com.acme.inventory.service.StockService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(StockController.class)
class StockControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private StockService stockService;

    @Test
    void getStock_returnsLevelsPerWarehouse() throws Exception {
        when(stockService.getStock(10L)).thenReturn(List.of(
                stockLevel(1L, 10L, "BER1", 10, 4),
                stockLevel(2L, 10L, "HAM2", 3, 0)));

        mockMvc.perform(get("/api/v1/products/10/stock"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].warehouseCode").value("BER1"))
                .andExpect(jsonPath("$[0].available").value(6))
                .andExpect(jsonPath("$[1].onHand").value(3));
    }

    @Test
    void receive_returnsUpdatedLevel() throws Exception {
        when(stockService.receive(10L, "BER1", 20, "PO-1")).thenReturn(stockLevel(1L, 10L, "BER1", 20, 0));

        mockMvc.perform(post("/api/v1/products/10/stock/receipts")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"warehouseCode": "BER1", "quantity": 20, "reference": "PO-1"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.onHand").value(20));
    }

    @Test
    void receive_rejectsNonPositiveQuantity() throws Exception {
        mockMvc.perform(post("/api/v1/products/10/stock/receipts")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"warehouseCode": "BER1", "quantity": 0, "reference": "PO-1"}
                                """))
                .andExpect(status().isBadRequest());
    }

    @Test
    void adjust_returns409WhenStockWouldGoNegative() throws Exception {
        when(stockService.adjust(10L, "BER1", -50, "stocktake"))
                .thenThrow(new InsufficientStockException(10L, "BER1", 10, 50));

        mockMvc.perform(post("/api/v1/products/10/stock/adjustments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"warehouseCode": "BER1", "delta": -50, "reason": "stocktake"}
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"));
    }

    @Test
    void reconcileCount_returnsReconciledLevel() throws Exception {
        when(stockService.reconcileCount(10L, "BER1", 37, "CC-2024-118"))
                .thenReturn(stockLevel(1L, 10L, "BER1", 37, 5));

        mockMvc.perform(post("/api/v1/products/10/stock/counts")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"warehouseCode": "BER1", "countedQuantity": 37, "countId": "CC-2024-118"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.onHand").value(37))
                .andExpect(jsonPath("$.available").value(32));
    }

    @Test
    void reconcileCount_rejectsNegativeCount() throws Exception {
        mockMvc.perform(post("/api/v1/products/10/stock/counts")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"warehouseCode": "BER1", "countedQuantity": -1, "countId": "CC-2024-118"}
                                """))
                .andExpect(status().isBadRequest());
    }
}
