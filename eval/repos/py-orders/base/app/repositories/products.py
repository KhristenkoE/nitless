from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, product_id: int) -> Product | None:
        return self._session.get(Product, product_id)

    def get_many(self, product_ids: Iterable[int]) -> dict[int, Product]:
        ids = set(product_ids)
        if not ids:
            return {}
        rows = self._session.scalars(select(Product).where(Product.id.in_(ids))).all()
        return {product.id: product for product in rows}

    def sku_exists(self, sku: str) -> bool:
        return self._session.scalar(select(func.count()).where(Product.sku == sku)) != 0

    def list_active(self, *, limit: int, offset: int) -> tuple[list[Product], int]:
        query = select(Product).where(Product.active.is_(True))
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(query.order_by(Product.name, Product.id).limit(limit).offset(offset)).all()
        return list(rows), total

    def add(self, product: Product) -> None:
        self._session.add(product)
        self._session.flush()
