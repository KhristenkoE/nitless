package com.acme.inventory.service;

import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.repository.ProductRepository;
import com.acme.inventory.repository.StockLevelRepository;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class StockService {

    private final StockLedger ledger;
    private final StockLevelRepository stockLevels;
    private final ProductRepository products;

    public StockService(StockLedger ledger, StockLevelRepository stockLevels, ProductRepository products) {
        this.ledger = ledger;
        this.stockLevels = stockLevels;
        this.products = products;
    }

    @Transactional(readOnly = true)
    public List<StockLevel> getStock(long productId) {
        requireProduct(productId);
        return stockLevels.findByProductIdOrderByWarehouseCode(productId);
    }

    @Transactional
    public StockLevel receive(long productId, String warehouseCode, long quantity, String reference) {
        requireProduct(productId);
        StockLevel level = ledger.lockOrCreate(productId, warehouseCode);
        ledger.record(level, MovementType.RECEIPT, quantity, reference);
        return level;
    }

    @Transactional
    public StockLevel adjust(long productId, String warehouseCode, long delta, String reason) {
        StockLevel level = ledger.lock(productId, warehouseCode);
        ledger.record(level, MovementType.ADJUSTMENT, delta, reason);
        return level;
    }

    /**
     * Books goods that left the warehouse without going through a reservation, e.g. B2B pallet
     * orders picked directly by the warehouse team. Only unreserved stock can be shipped this way.
     */
    @Transactional
    public StockLevel ship(long productId, String warehouseCode, long quantity, String reference) {
        requireProduct(productId);
        StockLevel level = ledger.lock(productId, warehouseCode);
        ledger.record(level, MovementType.SHIPMENT, -quantity, reference);
        return level;
    }

    private void requireProduct(long productId) {
        if (!products.existsById(productId)) {
            throw new ProductNotFoundException(productId);
        }
    }
}
