package com.acme.inventory.service;

import static com.acme.inventory.TestData.stockLevel;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.acme.inventory.common.ProductNotFoundException;
import com.acme.inventory.domain.MovementType;
import com.acme.inventory.domain.StockLevel;
import com.acme.inventory.repository.ProductRepository;
import com.acme.inventory.repository.StockLevelRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class StockServiceTest {

    @Mock
    private StockLedger ledger;

    @Mock
    private StockLevelRepository stockLevels;

    @Mock
    private ProductRepository products;

    private StockService stockService;

    @BeforeEach
    void setUp() {
        stockService = new StockService(ledger, stockLevels, products);
    }

    @Test
    void receive_recordsReceiptOnLockedLevel() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 0, 0);
        when(products.existsById(10L)).thenReturn(true);
        when(ledger.lockOrCreate(10L, "BER1")).thenReturn(level);

        StockLevel result = stockService.receive(10L, "BER1", 50, "PO-77");

        assertThat(result).isSameAs(level);
        verify(ledger).record(level, MovementType.RECEIPT, 50, "PO-77");
    }

    @Test
    void receive_failsForUnknownProduct() {
        when(products.existsById(anyLong())).thenReturn(false);

        assertThatThrownBy(() -> stockService.receive(99L, "BER1", 5, "PO-1"))
                .isInstanceOf(ProductNotFoundException.class);
        verifyNoInteractions(ledger);
    }

    @Test
    void adjust_recordsSignedDelta() {
        StockLevel level = stockLevel(1L, 10L, "BER1", 10, 0);
        when(ledger.lock(10L, "BER1")).thenReturn(level);

        stockService.adjust(10L, "BER1", -2, "broken pallet");

        verify(ledger).record(level, MovementType.ADJUSTMENT, -2, "broken pallet");
    }
}
