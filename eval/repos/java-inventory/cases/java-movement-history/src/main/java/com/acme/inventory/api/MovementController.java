package com.acme.inventory.api;

import com.acme.inventory.api.dto.MovementResponse;
import com.acme.inventory.api.dto.PageResponse;
import com.acme.inventory.service.MovementHistoryService;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/products/{productId}/movements")
public class MovementController {

    private static final int MAX_PAGE_SIZE = 200;

    private final MovementHistoryService movementHistoryService;

    public MovementController(MovementHistoryService movementHistoryService) {
        this.movementHistoryService = movementHistoryService;
    }

    @GetMapping
    public PageResponse<MovementResponse> history(@PathVariable long productId,
                                                  @RequestParam(required = false) String warehouse,
                                                  @RequestParam(defaultValue = "0") int page,
                                                  @RequestParam(defaultValue = "50") int size) {
        PageRequest pageable = PageRequest.of(page, Math.min(size, MAX_PAGE_SIZE),
                Sort.by(Sort.Direction.DESC, "occurredAt", "id"));
        return PageResponse.from(movementHistoryService.history(productId, warehouse, pageable),
                MovementResponse::from);
    }
}
