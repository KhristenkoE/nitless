package com.acme.inventory.service;

import com.acme.inventory.common.InsufficientStockException;
import com.acme.inventory.common.InvalidRequestException;
import com.acme.inventory.common.StockLevelNotFoundException;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.domain.StockMovement;
import com.acme.inventory.repository.StockLevelRepository;
import com.acme.inventory.repository.StockMovementRepository;
import java.time.Clock;
import java.time.Instant;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Applies stock movements to stock levels and keeps the movement history.
 * Callers must run inside a transaction and hold the row lock obtained from {@link #lock}.
 */
@Service
public class StockLedger {

    private final StockLevelRepository stockLevels;
    private final StockMovementRepository movements;
    private final Clock clock;

    public StockLedger(StockLevelRepository stockLevels, StockMovementRepository movements, Clock clock) {
        this.stockLevels = stockLevels;
        this.movements = movements;
        this.clock = clock;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public StockLevel lock(long productId, String warehouseCode) {
        return stockLevels.findForUpdate(productId, warehouseCode)
                .orElseThrow(() -> new StockLevelNotFoundException(productId, warehouseCode));
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public StockLevel lockOrCreate(long productId, String warehouseCode) {
        return stockLevels.findForUpdate(productId, warehouseCode)
                .orElseGet(() -> stockLevels.saveAndFlush(new StockLevel(productId, warehouseCode, clock.instant())));
    }

    /**
     * Applies a movement to a locked stock level and appends it to the history.
     *
     * @param quantity amount moved; the direction comes from {@code type} (see {@link MovementType}),
     *                 except for {@link MovementType#ADJUSTMENT} where the caller passes a signed delta
     */
    @Transactional(propagation = Propagation.MANDATORY)
    public StockMovement record(StockLevel level, MovementType type, long quantity, String reference) {
        if (quantity == 0) {
            throw new InvalidRequestException("Movement quantity must not be zero");
        }
        long onHand = level.getQuantity() + type.onHandSign() * quantity;
        long reserved = level.getReserved() + type.reservedSign() * quantity;
        if (reserved < 0 || onHand < reserved) {
            throw new InsufficientStockException(level.getProductId(), level.getWarehouseCode(),
                    level.getAvailable(), Math.abs(quantity));
        }
        Instant now = clock.instant();
        level.setQuantity(onHand);
        level.setReserved(reserved);
        level.setUpdatedAt(now);
        return movements.save(new StockMovement(level, type, quantity, reference, now));
    }
}
