package com.acme.inventory.api;

import com.acme.inventory.api.dto.CreateProductRequest;
import com.acme.inventory.api.dto.PageResponse;
import com.acme.inventory.api.dto.ProductResponse;
import com.acme.inventory.service.ProductService;
import jakarta.validation.Valid;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/products")
public class ProductController {

    private static final int MAX_PAGE_SIZE = 100;

    private final ProductService productService;

    public ProductController(ProductService productService) {
        this.productService = productService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ProductResponse create(@Valid @RequestBody CreateProductRequest request) {
        return ProductResponse.from(productService.create(request.sku(), request.name(), request.description()));
    }

    @GetMapping("/{productId}")
    public ProductResponse get(@PathVariable long productId) {
        return ProductResponse.from(productService.get(productId));
    }

    @GetMapping("/by-sku/{sku}")
    public ProductResponse getBySku(@PathVariable String sku) {
        return ProductResponse.from(productService.getBySku(sku));
    }

    @GetMapping
    public PageResponse<ProductResponse> list(@RequestParam(defaultValue = "0") int page,
                                              @RequestParam(defaultValue = "20") int size) {
        PageRequest pageable = PageRequest.of(page, Math.min(size, MAX_PAGE_SIZE), Sort.by("sku"));
        return PageResponse.from(productService.list(pageable), ProductResponse::from);
    }
}
