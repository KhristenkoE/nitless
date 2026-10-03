package com.acme.inventory.service;

import static com.acme.inventory.TestData.NOW;
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
import com.acme.inventory.repository.ProductRepository;
import java.time.Clock;
import java.time.ZoneOffset;
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

    private ProductService productService;

    @BeforeEach
    void setUp() {
        productService = new ProductService(products, Clock.fixed(NOW, ZoneOffset.UTC));
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
}
