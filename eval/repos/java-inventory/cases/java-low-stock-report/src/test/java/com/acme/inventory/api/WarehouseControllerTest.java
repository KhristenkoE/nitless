package com.acme.inventory.api;

import static com.acme.inventory.TestData.stockLevel;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.acme.inventory.service.StockService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(WarehouseController.class)
class WarehouseControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private StockService stockService;

    @Test
    void lowStock_usesConfiguredThresholdByDefault() throws Exception {
        when(stockService.lowStock("BER1", 10)).thenReturn(List.of(
                stockLevel(3L, 12L, "BER1", 4, 4),
                stockLevel(1L, 10L, "BER1", 9, 2)));

        mockMvc.perform(get("/api/v1/warehouses/BER1/low-stock"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].productId").value(12))
                .andExpect(jsonPath("$[0].available").value(0))
                .andExpect(jsonPath("$[1].available").value(7));
    }

    @Test
    void lowStock_acceptsThresholdOverride() throws Exception {
        when(stockService.lowStock("BER1", 50)).thenReturn(List.of(stockLevel(1L, 10L, "BER1", 30, 0)));

        mockMvc.perform(get("/api/v1/warehouses/BER1/low-stock").param("threshold", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].available").value(30));
    }

    @Test
    void lowStock_rejectsNonNumericThreshold() throws Exception {
        mockMvc.perform(get("/api/v1/warehouses/BER1/low-stock").param("threshold", "many"))
                .andExpect(status().isBadRequest());
    }
}
