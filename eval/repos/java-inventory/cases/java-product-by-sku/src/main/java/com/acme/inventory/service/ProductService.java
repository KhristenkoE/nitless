package com.acme.inventory.service;

import com.acme.inventory.common.DuplicateSkuException;
import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.domain.Product;
import com.acme.inventory.repository.ProductRepository;
import java.time.Clock;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ProductService {

    private final ProductRepository products;
    private final Clock clock;

    public ProductService(ProductRepository products, Clock clock) {
        this.products = products;
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
    public Product getBySku(String sku) {
        return products.findBySku(sku).orElseThrow(() -> new ProductNotFoundException(sku));
    }

    @Transactional(readOnly = true)
    public Page<Product> list(Pageable pageable) {
        return products.findAll(pageable);
    }
}
