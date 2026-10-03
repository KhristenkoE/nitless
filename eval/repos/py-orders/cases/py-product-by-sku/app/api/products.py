from fastapi import APIRouter, Depends, Query

from app.api.deps import get_catalog_service, get_principal
from app.schemas.common import Page
from app.schemas.product import ProductOut
from app.services.catalog import CatalogService

router = APIRouter(prefix="/products", tags=["products"], dependencies=[Depends(get_principal)])


@router.get("", response_model=Page[ProductOut])
def list_products(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: CatalogService = Depends(get_catalog_service),
) -> Page[ProductOut]:
    products, total = service.list_products(limit=limit, offset=offset)
    return Page[ProductOut](
        items=[ProductOut.model_validate(product) for product in products], total=total, limit=limit, offset=offset
    )


@router.get("/by-sku/{sku}", response_model=ProductOut)
def get_product_by_sku(sku: str, service: CatalogService = Depends(get_catalog_service)) -> ProductOut:
    return ProductOut.model_validate(service.get_product_by_sku(sku))


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, service: CatalogService = Depends(get_catalog_service)) -> ProductOut:
    return ProductOut.model_validate(service.get_product(product_id))
