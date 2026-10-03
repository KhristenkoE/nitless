package com.acme.inventory;

import com.acme.inventory.domain.Product;
import com.acme.inventory.domain.Reservation;
import com.acme.inventory.domain.StockLevel;
import java.time.Duration;
import java.time.Instant;
import org.springframework.test.util.ReflectionTestUtils;

public final class TestData {

    public static final Instant NOW = Instant.parse("2024-06-03T08:15:00Z");

    private TestData() {
    }

    public static Product product(long id, String sku) {
        Product product = new Product(sku, "Product " + sku, null, NOW);
        ReflectionTestUtils.setField(product, "id", id);
        return product;
    }

    public static StockLevel stockLevel(long id, long productId, String warehouseCode, long onHand, long reserved) {
        StockLevel level = new StockLevel(productId, warehouseCode, NOW);
        ReflectionTestUtils.setField(level, "id", id);
        level.setQuantity(onHand);
        level.setReserved(reserved);
        return level;
    }

    public static Reservation reservation(long id, long productId, String warehouseCode, long quantity) {
        Reservation reservation = new Reservation(productId, warehouseCode, quantity, "SO-" + id, NOW,
                NOW.plus(Duration.ofMinutes(30)));
        ReflectionTestUtils.setField(reservation, "id", id);
        return reservation;
    }
}
