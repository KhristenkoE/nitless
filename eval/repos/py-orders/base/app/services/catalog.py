from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.product import Product
from app.repositories.products import ProductRepository
from app.schemas.product import ProductCreate

log = get_logger(__name__)


class CatalogService:
    def __init__(self, session: Session) -> None:
        self._products = ProductRepository(session)

    def list_products(self, *, limit: int, offset: int) -> tuple[list[Product], int]:
        return self._products.list_active(limit=limit, offset=offset)

    def get_product(self, product_id: int) -> Product:
        product = self._products.get(product_id)
        if product is None or not product.active:
            raise NotFoundError("product not found", product_id=product_id)
        return product

    def create_product(self, data: ProductCreate) -> Product:
        if self._products.sku_exists(data.sku):
            raise ConflictError("a product with this SKU already exists", sku=data.sku)
        product = Product(**data.model_dump(), active=True)
        self._products.add(product)
        log.info("product_created", product_id=product.id, sku=product.sku)
        return product
