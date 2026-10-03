package com.acme.inventory.api;

import com.acme.inventory.api.dto.StockLevelResponse;
import com.acme.inventory.service.StockService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/warehouses/{warehouseCode}")
public class WarehouseController {

    private final StockService stockService;

    public WarehouseController(StockService stockService) {
        this.stockService = stockService;
    }

    /** Replenishment report: every product in the warehouse whose available quantity is below the threshold. */
    @GetMapping("/low-stock")
    public List<StockLevelResponse> lowStock(
            @PathVariable String warehouseCode,
            @RequestParam(defaultValue = "${inventory.low-stock-threshold}") long threshold) {
        return stockService.lowStock(warehouseCode, threshold).stream()
                .map(StockLevelResponse::from)
                .toList();
    }
}
