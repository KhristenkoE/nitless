package com.acme.inventory.service;

import com.acme.inventory.common.InvalidRequestException;
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
     * Moves unreserved stock from one warehouse to another in a single transaction.
     *
     * @return the source and the target stock level, in that order
     */
    @Transactional
    public List<StockLevel> transfer(long productId, String fromWarehouse, String toWarehouse, long quantity,
                                     String reference) {
        if (fromWarehouse.equals(toWarehouse)) {
            throw new InvalidRequestException("Source and target warehouse must differ");
        }
        requireProduct(productId);
        StockLevel source;
        StockLevel target;
        if (fromWarehouse.compareTo(toWarehouse) < 0) {
            source = ledger.lock(productId, fromWarehouse);
            target = ledger.lockOrCreate(productId, toWarehouse);
        } else {
            target = ledger.lockOrCreate(productId, toWarehouse);
            source = ledger.lock(productId, fromWarehouse);
        }
        ledger.record(source, MovementType.SHIPMENT, quantity, "transfer-out:" + reference);
        ledger.record(target, MovementType.RECEIPT, quantity, "transfer-in:" + reference);
        return List.of(source, target);
    }

    private void requireProduct(long productId) {
        if (!products.existsById(productId)) {
            throw new ProductNotFoundException(productId);
        }
    }
}
