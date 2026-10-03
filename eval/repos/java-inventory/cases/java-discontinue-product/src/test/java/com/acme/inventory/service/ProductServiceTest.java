package com.acme.inventory.service;

import static com.acme.inventory.TestData.NOW;
import static com.acme.inventory.TestData.product;
import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.acme.inventory.common.DuplicateSkuException;
import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.domain.Product;
import com.acme.inventory.domain.ProductStatus;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.repository.ProductRepository;
import com.acme.inventory.repository.StockLevelRepository;
import java.time.Clock;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class ProductServiceTest {

    @Mock
    private ProductRepository products;

    @Mock
    private StockLevelRepository stockLevels;

    private ProductService productService;

    @BeforeEach
    void setUp() {
        productService = new ProductService(products, stockLevels, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void create_savesActiveProduct() {
        when(products.existsBySku("CHAIR-01")).thenReturn(false);
        when(products.save(any(Product.class))).thenAnswer(invocation -> invocation.getArgument(0));

        Product product = productService.create("CHAIR-01", "Office chair", "Black");

        assertThat(product.getStatus()).isEqualTo(ProductStatus.ACTIVE);
        assertThat(product.getCreatedAt()).isEqualTo(NOW);
    }

    @Test
    void create_rejectsDuplicateSku() {
        when(products.existsBySku("CHAIR-01")).thenReturn(true);

        assertThatThrownBy(() -> productService.create("CHAIR-01", "Office chair", null))
                .isInstanceOf(DuplicateSkuException.class);
        verify(products, never()).save(any());
    }

    @Test
    void get_throwsWhenMissing() {
        when(products.findById(5L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> productService.get(5L)).isInstanceOf(ProductNotFoundException.class);
    }

    @Test
    void discontinue_writesOffUnreservedStock() {
        StockLevel berlin = stockLevel(1L, 5L, "BER1", 12, 2);
        StockLevel hamburg = stockLevel(2L, 5L, "HAM2", 4, 0);
        when(products.findById(5L)).thenReturn(Optional.of(product(5L, "CHAIR-01")));
        when(stockLevels.findByProductIdOrderByWarehouseCode(5L)).thenReturn(List.of(berlin, hamburg));

        Product product = productService.discontinue(5L);

        assertThat(product.getStatus()).isEqualTo(ProductStatus.DISCONTINUED);
        assertThat(berlin.getQuantity()).isEqualTo(2);
        assertThat(berlin.getAvailable()).isZero();
        assertThat(hamburg.getQuantity()).isZero();
    }

    @Test
    void discontinue_isNoOpWhenAlreadyDiscontinued() {
        Product discontinued = product(5L, "CHAIR-01");
        discontinued.discontinue(NOW);
        when(products.findById(5L)).thenReturn(Optional.of(discontinued));

        productService.discontinue(5L);

        verify(stockLevels, never()).findByProductIdOrderByWarehouseCode(any());
    }
}
