package com.acme.inventory.service;

import com.acme.inventory.common.DuplicateSkuException;
import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.domain.Product;
import com.acme.inventory.domain.ProductStatus;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.repository.ProductRepository;
import com.acme.inventory.repository.StockLevelRepository;
import java.time.Clock;
import java.time.Instant;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ProductService {

    private final ProductRepository products;
    private final StockLevelRepository stockLevels;
    private final Clock clock;

    public ProductService(ProductRepository products, StockLevelRepository stockLevels, Clock clock) {
        this.products = products;
        this.stockLevels = stockLevels;
        this.clock = clock;
    }

    @Transactional
    public Product create(String sku, String name, String description) {
        if (products.existsBySku(sku)) {
            throw new DuplicateSkuException(sku);
        }
        return products.save(new Product(sku, name, description, clock.instant()));
    }

    @Transactional(readOnly = true)
    public Product get(long productId) {
        return products.findById(productId).orElseThrow(() -> new ProductNotFoundException(productId));
    }

    @Transactional(readOnly = true)
    public Page<Product> list(Pageable pageable) {
        return products.findAll(pageable);
    }

    /**
     * Takes a product out of the assortment. Unreserved stock is written off in every warehouse so
     * it can no longer be reserved; units held by open reservations stay and can still be fulfilled.
     * Discontinuing an already discontinued product is a no-op.
     */
    @Transactional
    public Product discontinue(long productId) {
        Product product = products.findById(productId).orElseThrow(() -> new ProductNotFoundException(productId));
        if (product.getStatus() == ProductStatus.DISCONTINUED) {
            return product;
        }
        Instant now = clock.instant();
        product.discontinue(now);
        for (StockLevel level : stockLevels.findByProductIdOrderByWarehouseCode(productId)) {
            level.setQuantity(level.getReserved());
            level.setUpdatedAt(now);
        }
        return product;
    }
}
