# implement reporting functionality


from __future__ import annotations
from datetime import UTC, datetime
from decimal import Decimal
from sqlalchemy import func, select
from database.create_db import db
from models import Customer, InventoryItem, Sale, SaleItem


SMALL_GROUP_LIMIT = 3
STATUSES = ("In stock", "Low stock", "Out of stock")


# avoid floating point imprecision
def _money(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# stop business users identifying a customer
# show a label instead
def hide_small(count: int, role: str) -> int | str:
    return (
        "Fewer than 3"
        if role == "Business" and 0 < count < SMALL_GROUP_LIMIT
        else count
    )


def stock_status(item: InventoryItem) -> str:
    if item.quantity == 0:
        return "Out of stock"
    return "Low stock" if item.quantity <= item.reorder_level else "In stock"


def inventory_status_summary() -> dict:
    # load items in name order
    items = db.session.scalars(
        select(InventoryItem)
        .where(InventoryItem.is_active.is_(True))
        .order_by(InventoryItem.name)
    ).all()
    # prepare for report
    rows = [
        {
            "sku": item.sku,
            "name": item.name,
            "quantity": item.quantity,
            "reorder_level": item.reorder_level,
            "status": stock_status(item),
        }
        for item in items
    ]
    return {
        "active_items": len(items),
        "units": sum(item.quantity for item in items),
        "low_items": sum(1 for item in items if item.quantity <= item.reorder_level),
        "rows": rows,
    }


def products_sold(filters: list, limit: int = 20) -> dict:
    # db caluclations for sales totals
    revenue = func.sum(SaleItem.quantity * SaleItem.unit_price)
    units = func.sum(SaleItem.quantity)
    # join tables and apply filters - group so products get one row each
    rows = db.session.execute(
        select(InventoryItem.sku, InventoryItem.name, units, revenue)
        .join(SaleItem, SaleItem.item_id == InventoryItem.item_id)
        .join(Sale, Sale.sale_id == SaleItem.sale_id)
        .where(*filters)
        .group_by(InventoryItem.item_id, InventoryItem.sku, InventoryItem.name)
        .order_by(units.desc(), InventoryItem.name)
    ).all()
    products = [
        {
            "sku": sku,
            "name": name,
            "units": int(quantity),
            "revenue": f"{_money(total):.2f}",
        }
        for sku, name, quantity, total in rows[:limit]
    ]
    return {
        "products": products,
        "distinct_products": len(rows),
        "units_sold": sum(int(row[2]) for row in rows),
        "shown": len(products),
    }


def customer_metrics(filters: list, role: str) -> dict:
    active_customers = (
        db.session.scalar(
            select(func.count())
            .select_from(Customer)
            .where(Customer.is_active.is_(True))
        )
        or 0
    )
    # count sales and total spend per customer
    period = db.session.execute(
        select(
            Sale.customer_id,
            func.count(),
            func.coalesce(func.sum(Sale.total), 0),
        )
        .where(Sale.customer_id.is_not(None), *filters)
        .group_by(Sale.customer_id)
    ).all()
    # calculate average order value
    purchases = sum(int(row[1]) for row in period)
    spend = sum(
        (_money(row[2]) for row in period),
        Decimal("0.00"),
    )
    # group customers by how many purchases made
    frequency = {
        "1 purchase": sum(1 for row in period if row[1] == 1),
        "2 to 3 purchases": sum(1 for row in period if 2 <= row[1] <= 3),
        "4 or more purchases": sum(1 for row in period if row[1] >= 4),
    }
    average_order_value = spend / purchases if purchases else Decimal("0.00")
    return {
        "active_customers": active_customers,
        "spend": f"{spend:.2f}",
        "average_order_value": f"{average_order_value:.2f}",
        "frequency": {
            label: hide_small(count, role) for label, count in frequency.items()
        },
    }