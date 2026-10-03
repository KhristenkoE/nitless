package com.acme.inventory.api;

import com.acme.inventory.api.dto.AdjustStockRequest;
import com.acme.inventory.api.dto.CycleCountRequest;
import com.acme.inventory.api.dto.ReceiveStockRequest;
import com.acme.inventory.api.dto.StockLevelResponse;
import com.acme.inventory.service.StockService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/products/{productId}/stock")
public class StockController {

    private final StockService stockService;

    public StockController(StockService stockService) {
        this.stockService = stockService;
    }

    @GetMapping
    public List<StockLevelResponse> getStock(@PathVariable long productId) {
        return stockService.getStock(productId).stream().map(StockLevelResponse::from).toList();
    }

    @PostMapping("/receipts")
    public StockLevelResponse receive(@PathVariable long productId,
                                      @Valid @RequestBody ReceiveStockRequest request) {
        return StockLevelResponse.from(
                stockService.receive(productId, request.warehouseCode(), request.quantity(), request.reference()));
    }

    @PostMapping("/adjustments")
    public StockLevelResponse adjust(@PathVariable long productId,
                                     @Valid @RequestBody AdjustStockRequest request) {
        return StockLevelResponse.from(
                stockService.adjust(productId, request.warehouseCode(), request.delta(), request.reason()));
    }

    @PostMapping("/counts")
    public StockLevelResponse reconcileCount(@PathVariable long productId,
                                             @Valid @RequestBody CycleCountRequest request) {
        return StockLevelResponse.from(stockService.reconcileCount(productId, request.warehouseCode(),
                request.countedQuantity(), request.countId()));
    }
}
