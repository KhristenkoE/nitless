package com.acme.inventory.api;

import static com.acme.inventory.TestData.product;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.acme.inventory.common.DuplicateSkuException;
import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.service.ProductService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(ProductController.class)
class ProductControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private ProductService productService;

    @Test
    void create_returns201() throws Exception {
        when(productService.create("CHAIR-01", "Office chair", null)).thenReturn(product(1L, "CHAIR-01"));

        mockMvc.perform(post("/api/v1/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"sku": "CHAIR-01", "name": "Office chair"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.status").value("ACTIVE"));
    }

    @Test
    void create_returns409ForDuplicateSku() throws Exception {
        when(productService.create("CHAIR-01", "Office chair", null)).thenThrow(new DuplicateSkuException("CHAIR-01"));

        mockMvc.perform(post("/api/v1/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"sku": "CHAIR-01", "name": "Office chair"}
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("DUPLICATE_SKU"));
    }

    @Test
    void create_returns400ForInvalidSku() throws Exception {
        mockMvc.perform(post("/api/v1/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"sku": "chair 01", "name": "Office chair"}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void get_returns404WhenMissing() throws Exception {
        when(productService.get(9L)).thenThrow(new ProductNotFoundException(9L));

        mockMvc.perform(get("/api/v1/products/9"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("PRODUCT_NOT_FOUND"));
    }

    @Test
    void list_capsPageSize() throws Exception {
        when(productService.list(any())).thenReturn(new PageImpl<>(List.of(product(1L, "CHAIR-01")),
                PageRequest.of(0, 100), 1));

        mockMvc.perform(get("/api/v1/products").param("size", "500"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.size").value(100))
                .andExpect(jsonPath("$.items[0].sku").value("CHAIR-01"));
    }
}
