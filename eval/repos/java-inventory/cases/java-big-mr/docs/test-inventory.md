# Test inventory

The automated tests by file, for the release audit trail; a parameterized test is listed once,
with its placeholders. Regenerate it when tests change. 88 tests are listed.

## `src/test/java/com/acme/inventory/api/GlobalExceptionHandlerTest.java` (4)

- handleInventoryException_mapsNotFoundErrorTo404
- handleInventoryException_mapsInsufficientStockTo409
- handleValidation_reportsFieldError
- handleValidation_joinsFieldErrorsInReportedOrder

## `src/test/java/com/acme/inventory/api/ProductControllerTest.java` (7)

- create_returns201
- create_returns409ForDuplicateSku
- create_returns400ForInvalidSku
- get_returns404WhenMissing
- list_capsPageSize
- discontinue_returnsDiscontinuedProduct
- discontinue_returns404WhenMissing

## `src/test/java/com/acme/inventory/api/ReservationControllerTest.java` (6)

- reserve_returns201
- reserve_returns409WhenNotEnoughStock
- get_returns404WhenMissing
- release_returns409WhenAlreadyFulfilled
- releasePartially_returnsRemainingQuantity
- releasePartially_returns400WhenReleasingEverything

## `src/test/java/com/acme/inventory/api/StockControllerTest.java` (6)

- getStock_returnsLevelsPerWarehouse
- receive_returnsUpdatedLevel
- receive_rejectsNonPositiveQuantity
- adjust_returns409WhenStockWouldGoNegative
- ship_returnsUpdatedLevel
- ship_returns409WhenStockIsReserved

## `src/test/java/com/acme/inventory/api/dto/PageResponseTest.java` (2)

- from_mapsItemsAndCopiesPaging
- from_returnsEmptyResponseForEmptyPage

## `src/test/java/com/acme/inventory/api/dto/RequestValidationTest.java` (13)

- receiveStock_acceptsValidRequest
- receiveStock_rejectsNonPositiveQuantity
- receiveStock_rejectsBlankWarehouseCodeAndReference
- receiveStock_limitsWarehouseCodeTo16Characters
- adjustStock_acceptsNegativeDelta
- adjustStock_rejectsMissingWarehouseCode
- adjustStock_limitsReasonTo128Characters
- createReservation_acceptsValidRequest
- createReservation_rejectsNonPositiveProductIdAndQuantity
- createReservation_limitsOrderReferenceTo64Characters
- createProduct_acceptsRequestWithoutDescription
- createProduct_rejectsSkuOutsideUppercaseDigitsAndDashes
- createProduct_limitsNameAndDescriptionLength

## `src/test/java/com/acme/inventory/api/dto/StockLevelResponseTest.java` (1)

- from_exposesOnHandReservedAndAvailableQuantity

## `src/test/java/com/acme/inventory/common/ErrorCodeTest.java` (1)

- status_mapsEachCodeToItsHttpStatus

## `src/test/java/com/acme/inventory/common/InventoryExceptionTest.java` (7)

- productNotFound_namesTheProduct
- duplicateSku_namesTheSku
- stockLevelNotFound_namesProductAndWarehouse
- insufficientStock_reportsAvailableAndRequestedQuantity
- reservationNotFound_namesTheReservation
- reservationState_namesCurrentStatusAndRejectedAction
- invalidRequest_keepsTheGivenMessage

## `src/test/java/com/acme/inventory/domain/MovementTypeTest.java` (1)

- signs_describeEffectOnOnHandAndReserved

## `src/test/java/com/acme/inventory/domain/StockLevelTest.java` (4)

- constructor_startsWithoutStock
- getAvailable_excludesReservedUnits
- getAvailable_isZeroWhenEverythingIsReserved
- getAvailable_followsChangesToOnHandAndReserved

## `src/test/java/com/acme/inventory/domain/StockMovementTest.java` (2)

- constructor_copiesIdentityAndQuantitiesOfTheLevel
- constructor_isNotAffectedByLaterChangesToTheLevel

## `src/test/java/com/acme/inventory/service/ProductServiceTest.java` (5)

- create_savesActiveProduct
- create_rejectsDuplicateSku
- get_throwsWhenMissing
- discontinue_writesOffUnreservedStock
- discontinue_isNoOpWhenAlreadyDiscontinued

## `src/test/java/com/acme/inventory/service/ReservationExpiryJobTest.java` (3)

- expiresEveryDueReservation
- continuesWhenOneReservationWasAlreadyClosed
- doesNothingWhenNoReservationIsDue

## `src/test/java/com/acme/inventory/service/ReservationServiceTest.java` (4)

- reserve_locksLevelRecordsMovementAndSetsExpiry
- release_releasesReservedQuantity
- release_rejectsReservationThatIsNoLongerActive
- fulfill_consumesReservedStock

## `src/test/java/com/acme/inventory/service/StockLedgerMovementTest.java` (10)

- lockOrCreate_returnsExistingStockLevelWithoutInserting
- lockOrCreate_insertsEmptyStockLevelWhenNoneExists
- record_savesSnapshotOfLevelAfterTheMovement
- record_shipmentDecreasesOnHandOnly
- record_releaseDecreasesReservedOnly
- record_allowsReservingAllAvailableStock
- record_keepsSignOfAdjustmentQuantityInHistory
- record_rejectsShipmentThatWouldConsumeReservedStock
- record_rejectsReleasingMoreThanIsReserved
- record_reportsAbsoluteQuantityOfRejectedNegativeAdjustment

## `src/test/java/com/acme/inventory/service/StockLedgerTest.java` (7)

- record_receiptIncreasesOnHand
- record_reserveIncreasesReservedOnly
- record_fulfillDecreasesOnHandAndReserved
- record_negativeAdjustmentDecreasesOnHand
- record_rejectsMovementThatWouldConsumeReservedStock
- record_rejectsZeroQuantity
- lock_throwsWhenStockLevelDoesNotExist

## `src/test/java/com/acme/inventory/service/StockServiceTest.java` (5)

- receive_recordsReceiptOnLockedLevel
- receive_failsForUnknownProduct
- adjust_recordsSignedDelta
- ship_recordsShipmentOnLockedLevel
- ship_failsForUnknownProduct
