# API reference

The public functions, classes and methods of every module with their signatures, as of this
release. Tests and migrations are not listed.

## `src/main/java/com/acme/inventory/InventoryApplication.java`

- `public class InventoryApplication`
  - `public static void main(String[] args)`

## `src/main/java/com/acme/inventory/api/GlobalExceptionHandler.java`

- `public class GlobalExceptionHandler`
  - `public ResponseEntity<ErrorResponse> handleInventoryException(InventoryException ex)`
  - `public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException ex)`

## `src/main/java/com/acme/inventory/api/ProductController.java`

- `public class ProductController`
  - `public ProductController(ProductService productService)`
  - `public ProductResponse create(@Valid @RequestBody CreateProductRequest request)`
  - `public ProductResponse get(@PathVariable long productId)`
  - `public PageResponse<ProductResponse> list(@RequestParam(defaultValue = "0") int page, @RequestParam(defaultValue = "20") int size)`
  - `public ProductResponse discontinue(@PathVariable long productId)`

## `src/main/java/com/acme/inventory/api/ReservationController.java`

- `public class ReservationController`
  - `public ReservationController(ReservationService reservationService)`
  - `public ReservationResponse reserve(@Valid @RequestBody CreateReservationRequest request)`
  - `public ReservationResponse get(@PathVariable long reservationId)`
  - `public ReservationResponse release(@PathVariable long reservationId)`
  - `public ReservationResponse releasePartially(@PathVariable long reservationId, @Valid @RequestBody PartialReleaseRequest request)`
  - `public ReservationResponse fulfill(@PathVariable long reservationId)`

## `src/main/java/com/acme/inventory/api/StockController.java`

- `public class StockController`
  - `public StockController(StockService stockService)`
  - `public List<StockLevelResponse> getStock(@PathVariable long productId)`
  - `public StockLevelResponse receive(@PathVariable long productId, @Valid @RequestBody ReceiveStockRequest request)`
  - `public StockLevelResponse adjust(@PathVariable long productId, @Valid @RequestBody AdjustStockRequest request)`
  - `public StockLevelResponse ship(@PathVariable long productId, @Valid @RequestBody ShipStockRequest request)`

## `src/main/java/com/acme/inventory/api/dto/AdjustStockRequest.java`

- `public record AdjustStockRequest( @NotBlank @Size(max = 16) String warehouseCode, long delta, @NotBlank @Size(max = 128) String reason)`

## `src/main/java/com/acme/inventory/api/dto/CreateProductRequest.java`

- `public record CreateProductRequest( @NotBlank @Size(max = 64) @Pattern(regexp = "[A-Z0-9-]+") String sku, @NotBlank @Size(max = 255) String name, @Size(max = 2000) String description)`

## `src/main/java/com/acme/inventory/api/dto/CreateReservationRequest.java`

- `public record CreateReservationRequest( @Positive long productId, @NotBlank @Size(max = 16) String warehouseCode, @Positive long quantity, @NotBlank @Size(max = 64) String orderReference)`

## `src/main/java/com/acme/inventory/api/dto/ErrorResponse.java`

- `public record ErrorResponse(String code, String message)`

## `src/main/java/com/acme/inventory/api/dto/PageResponse.java`

- `public record PageResponse<T>(List<T> items, int page, int size, long totalElements, int totalPages)`
  - `public static <E, T> PageResponse<T> from(Page<E> page, Function<E, T> mapper)`

## `src/main/java/com/acme/inventory/api/dto/PartialReleaseRequest.java`

- `public record PartialReleaseRequest(@Positive long quantity)`

## `src/main/java/com/acme/inventory/api/dto/ProductResponse.java`

- `public record ProductResponse( long id, String sku, String name, String description, String status, Instant createdAt, Instant updatedAt)`
  - `public static ProductResponse from(Product product)`

## `src/main/java/com/acme/inventory/api/dto/ReceiveStockRequest.java`

- `public record ReceiveStockRequest( @NotBlank @Size(max = 16) String warehouseCode, @Positive long quantity, @NotBlank @Size(max = 128) String reference)`

## `src/main/java/com/acme/inventory/api/dto/ReservationResponse.java`

- `public record ReservationResponse( long id, long productId, String warehouseCode, long quantity, String orderReference, String status, Instant expiresAt)`
  - `public static ReservationResponse from(Reservation reservation)`

## `src/main/java/com/acme/inventory/api/dto/ShipStockRequest.java`

- `public record ShipStockRequest( @NotBlank @Size(max = 16) String warehouseCode, @Positive long quantity, @NotBlank @Size(max = 128) String reference)`

## `src/main/java/com/acme/inventory/api/dto/StockLevelResponse.java`

- `public record StockLevelResponse( long productId, String warehouseCode, long onHand, long reserved, long available, Instant updatedAt)`
  - `public static StockLevelResponse from(StockLevel level)`

## `src/main/java/com/acme/inventory/common/DuplicateSkuException.java`

- `public class DuplicateSkuException extends InventoryException`
  - `public DuplicateSkuException(String sku)`

## `src/main/java/com/acme/inventory/common/ErrorCode.java`

- `public enum ErrorCode`
  - `public HttpStatus status()`

## `src/main/java/com/acme/inventory/common/InsufficientStockException.java`

- `public class InsufficientStockException extends InventoryException`
  - `public InsufficientStockException(long productId, String warehouseCode, long available, long requested)`

## `src/main/java/com/acme/inventory/common/InvalidRequestException.java`

- `public class InvalidRequestException extends InventoryException`
  - `public InvalidRequestException(String message)`

## `src/main/java/com/acme/inventory/common/InventoryException.java`

  - `public ErrorCode getErrorCode()`

## `src/main/java/com/acme/inventory/common/ProductNotFoundException.java`

- `public class ProductNotFoundException extends InventoryException`
  - `public ProductNotFoundException(long productId)`

## `src/main/java/com/acme/inventory/common/ReservationNotFoundException.java`

- `public class ReservationNotFoundException extends InventoryException`
  - `public ReservationNotFoundException(long reservationId)`

## `src/main/java/com/acme/inventory/common/ReservationStateException.java`

- `public class ReservationStateException extends InventoryException`
  - `public ReservationStateException(Long reservationId, String currentStatus, String action)`

## `src/main/java/com/acme/inventory/common/StockLevelNotFoundException.java`

- `public class StockLevelNotFoundException extends InventoryException`
  - `public StockLevelNotFoundException(long productId, String warehouseCode)`

## `src/main/java/com/acme/inventory/config/ClockConfig.java`

- `public class ClockConfig`
  - `public Clock clock()`

## `src/main/java/com/acme/inventory/config/InventoryProperties.java`

- `public record InventoryProperties( @NotNull Duration reservationTtl, @Positive int expiryBatchSize, @NotNull Duration expiryInterval)`

## `src/main/java/com/acme/inventory/domain/MovementType.java`

- `public enum MovementType`
  - `public int onHandSign()`
  - `public int reservedSign()`

## `src/main/java/com/acme/inventory/domain/Product.java`

- `public class Product`
  - `public Product(String sku, String name, String description, Instant now)`
  - `public void discontinue(Instant now)`
  - `public Long getId()`
  - `public String getSku()`
  - `public String getName()`
  - `public String getDescription()`
  - `public ProductStatus getStatus()`
  - `public Instant getCreatedAt()`
  - `public Instant getUpdatedAt()`

## `src/main/java/com/acme/inventory/domain/ProductStatus.java`

- `public enum ProductStatus`

## `src/main/java/com/acme/inventory/domain/Reservation.java`

- `public class Reservation`
  - `public Reservation(Long productId, String warehouseCode, long quantity, String orderReference, Instant now, Instant expiresAt)`
  - `public void release(Instant now)`
  - `public void fulfill(Instant now)`
  - `public void expire(Instant now)`
  - `public void releasePartially(long amount, Instant now)`
  - `public boolean isActive()`
  - `public Long getId()`
  - `public Long getProductId()`
  - `public String getWarehouseCode()`
  - `public long getQuantity()`
  - `public String getOrderReference()`
  - `public ReservationStatus getStatus()`
  - `public Instant getCreatedAt()`
  - `public Instant getExpiresAt()`
  - `public Instant getUpdatedAt()`

## `src/main/java/com/acme/inventory/domain/ReservationStatus.java`

- `public enum ReservationStatus`

## `src/main/java/com/acme/inventory/domain/StockLevel.java`

- `public class StockLevel`
  - `public StockLevel(Long productId, String warehouseCode, Instant now)`
  - `public Long getId()`
  - `public Long getProductId()`
  - `public String getWarehouseCode()`
  - `public long getQuantity()`
  - `public void setQuantity(long quantity)`
  - `public long getReserved()`
  - `public void setReserved(long reserved)`
  - `public long getAvailable()`
  - `public Instant getUpdatedAt()`
  - `public void setUpdatedAt(Instant updatedAt)`

## `src/main/java/com/acme/inventory/domain/StockMovement.java`

- `public class StockMovement`
  - `public StockMovement(StockLevel level, MovementType type, long quantity, String reference, Instant occurredAt)`
  - `public Long getId()`
  - `public Long getStockLevelId()`
  - `public Long getProductId()`
  - `public String getWarehouseCode()`
  - `public MovementType getType()`
  - `public long getQuantity()`
  - `public long getOnHandAfter()`
  - `public long getReservedAfter()`
  - `public String getReference()`
  - `public Instant getOccurredAt()`

## `src/main/java/com/acme/inventory/repository/ProductRepository.java`

- `public interface ProductRepository extends JpaRepository<Product, Long>`

## `src/main/java/com/acme/inventory/repository/ReservationRepository.java`

- `public interface ReservationRepository extends JpaRepository<Reservation, Long>`

## `src/main/java/com/acme/inventory/repository/StockLevelRepository.java`

- `public interface StockLevelRepository extends JpaRepository<StockLevel, Long>`

## `src/main/java/com/acme/inventory/repository/StockMovementRepository.java`

- `public interface StockMovementRepository extends JpaRepository<StockMovement, Long>`

## `src/main/java/com/acme/inventory/service/ProductService.java`

- `public class ProductService`
  - `public ProductService(ProductRepository products, StockLevelRepository stockLevels, Clock clock)`
  - `public Product create(String sku, String name, String description)`
  - `public Product get(long productId)`
  - `public Page<Product> list(Pageable pageable)`
  - `public Product discontinue(long productId)`

## `src/main/java/com/acme/inventory/service/ReservationExpiryJob.java`

- `public class ReservationExpiryJob`
  - `public ReservationExpiryJob(ReservationService reservationService, InventoryProperties properties)`
  - `public void expireDueReservations()`

## `src/main/java/com/acme/inventory/service/ReservationService.java`

- `public class ReservationService`
  - `public ReservationService(ReservationRepository reservations, ProductRepository products, StockLedger ledger, InventoryProperties properties, Clock clock)`
  - `public Reservation reserve(long productId, String warehouseCode, long quantity, String orderReference)`
  - `public Reservation get(long reservationId)`
  - `public Reservation release(long reservationId)`
  - `public Reservation releasePartially(long reservationId, long quantity)`
  - `public Reservation fulfill(long reservationId)`
  - `public List<Long> findExpiredIds(int limit)`
  - `public void expire(long reservationId)`

## `src/main/java/com/acme/inventory/service/StockLedger.java`

- `public class StockLedger`
  - `public StockLedger(StockLevelRepository stockLevels, StockMovementRepository movements, Clock clock)`
  - `public StockLevel lock(long productId, String warehouseCode)`
  - `public StockLevel lockOrCreate(long productId, String warehouseCode)`
  - `public StockMovement record(StockLevel level, MovementType type, long quantity, String reference)`

## `src/main/java/com/acme/inventory/service/StockService.java`

- `public class StockService`
  - `public StockService(StockLedger ledger, StockLevelRepository stockLevels, ProductRepository products)`
  - `public List<StockLevel> getStock(long productId)`
  - `public StockLevel receive(long productId, String warehouseCode, long quantity, String reference)`
  - `public StockLevel adjust(long productId, String warehouseCode, long delta, String reason)`
  - `public StockLevel ship(long productId, String warehouseCode, long quantity, String reference)`
