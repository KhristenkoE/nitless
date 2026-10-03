# inventory-service

Warehouse inventory service for the Acme fulfilment platform. It owns the product
catalogue, per-warehouse stock levels, stock reservations for open orders, and the
history of every stock movement.

## Domain

| Concept       | Description                                                                  |
|---------------|------------------------------------------------------------------------------|
| Product       | A SKU in the catalogue. Products are `ACTIVE` or `DISCONTINUED`.             |
| Stock level   | On-hand and reserved quantity of one product in one warehouse.               |
| Reservation   | Quantity held for an order until it is fulfilled, released or expires.       |
| Stock movement| One row per change to a stock level (receipt, adjustment, reservation, ...). |

Available quantity is `on_hand - reserved`. Reservations expire after
`inventory.reservation-ttl` (30 minutes by default); a scheduled job releases them.

## API

All endpoints live under `/api/v1`.

| Method | Path                                         | Purpose                         |
|--------|----------------------------------------------|---------------------------------|
| POST   | `/products`                                  | Create a product                |
| GET    | `/products`                                  | List products (paginated)       |
| GET    | `/products/{id}`                             | Get a product                   |
| GET    | `/products/{id}/stock`                       | Stock levels per warehouse      |
| POST   | `/products/{id}/stock/receipts`              | Book received goods             |
| POST   | `/products/{id}/stock/adjustments`           | Manual correction (+/-)         |
| POST   | `/reservations`                              | Reserve stock for an order      |
| GET    | `/reservations/{id}`                         | Get a reservation               |
| POST   | `/reservations/{id}/release`                 | Release a reservation           |
| POST   | `/reservations/{id}/fulfill`                 | Mark a reservation as shipped   |

Errors are returned as `{"code": "...", "message": "..."}`.

## Running locally

```bash
docker run -d --name inventory-db -e POSTGRES_DB=inventory -e POSTGRES_USER=inventory \
  -e POSTGRES_PASSWORD=inventory -p 5432:5432 postgres:16
./mvnw spring-boot:run
```

Configuration is in `src/main/resources/application.yml`; the datasource can be overridden
with `DB_URL`, `DB_USER` and `DB_PASSWORD`.

## Tests

```bash
./mvnw verify
```

`verify` also runs Checkstyle (`config/checkstyle/checkstyle.xml`).

## Decisions

Architecture decision records live in [`docs/adr`](docs/adr).
