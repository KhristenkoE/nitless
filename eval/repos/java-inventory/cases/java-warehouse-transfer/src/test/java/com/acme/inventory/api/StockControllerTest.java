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
    void transfer_returnsSourceAndTargetLevels() throws Exception {
        when(stockService.transfer(10L, "BER1", "HAM2", 12, "TR-81")).thenReturn(List.of(
                stockLevel(1L, 10L, "BER1", 18, 5),
                stockLevel(2L, 10L, "HAM2", 12, 0)));

        mockMvc.perform(post("/api/v1/products/10/stock/transfers")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"fromWarehouse": "BER1", "toWarehouse": "HAM2", "quantity": 12, "reference": "TR-81"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].available").value(13))
                .andExpect(jsonPath("$[1].onHand").value(12));
    }

    @Test
    void transfer_returns409WhenSourceHasNotEnoughStock() throws Exception {
        when(stockService.transfer(10L, "BER1", "HAM2", 50, "TR-81"))
                .thenThrow(new InsufficientStockException(10L, "BER1", 25, 50));

        mockMvc.perform(post("/api/v1/products/10/stock/transfers")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"fromWarehouse": "BER1", "toWarehouse": "HAM2", "quantity": 50, "reference": "TR-81"}
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("INSUFFICIENT_STOCK"));
    }
}
