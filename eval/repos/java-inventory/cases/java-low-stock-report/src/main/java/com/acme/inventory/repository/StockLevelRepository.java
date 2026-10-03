package com.acme.inventory.repository;

import com.acme.inventory.domain.StockLevel;
import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface StockLevelRepository extends JpaRepository<StockLevel, Long> {

    /** Non-locking read, for queries that do not modify the stock level. */
    Optional<StockLevel> findByProductIdAndWarehouseCode(Long productId, String warehouseCode);

    List<StockLevel> findByProductIdOrderByWarehouseCode(Long productId);

    /** {@code SELECT ... FOR UPDATE}; see docs/adr/0001-stock-level-concurrency.md. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select s from StockLevel s where s.productId = :productId and s.warehouseCode = :warehouseCode")
    Optional<StockLevel> findForUpdate(@Param("productId") Long productId,
                                       @Param("warehouseCode") String warehouseCode);

    /** Stock levels of a warehouse whose available quantity is below {@code threshold}, lowest first. */
    @Query("""
            select s from StockLevel s
            where s.warehouseCode = :warehouseCode and s.quantity - s.reserved < :threshold
            order by s.quantity - s.reserved, s.productId""")
    List<StockLevel> findLowStock(@Param("warehouseCode") String warehouseCode,
                                  @Param("threshold") long threshold);
}
