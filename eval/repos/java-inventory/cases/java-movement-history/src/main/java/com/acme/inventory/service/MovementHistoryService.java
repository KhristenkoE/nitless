package com.acme.inventory.service;

import com.acme.inventory.domain.StockMovement;
import com.acme.inventory.repository.StockMovementRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Read side of the stock ledger, for support and audits. */
@Service
public class MovementHistoryService {

    private final StockMovementRepository movements;

    public MovementHistoryService(StockMovementRepository movements) {
        this.movements = movements;
    }

    /**
     * Movements of a product, optionally restricted to one warehouse.
     *
     * @param warehouseCode warehouse to filter by, or {@code null} for all warehouses
     */
    @Transactional(readOnly = true)
    public Page<StockMovement> history(long productId, String warehouseCode, Pageable pageable) {
        if (warehouseCode == null) {
            return movements.findByProductId(productId, pageable);
        }
        return movements.findByProductIdAndWarehouseCode(productId, warehouseCode, pageable);
    }
}
