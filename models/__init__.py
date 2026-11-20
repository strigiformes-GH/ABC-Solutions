# define db tables


from datetime import UTC, datetime
from flask_login import UserMixin  # auth-related methods
from database.create_db import db
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)


# new records use UTC
def utc_now() -> datetime:
    return datetime.now(UTC)


# roles
class Role(db.Model):
    __tablename__ = "roles"

    # role attributes
    role_id = db.Column(Integer, primary_key=True, autoincrement=True)
    name = db.Column(String(20), nullable=False, unique=True)


# users
class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(first_name) <= 50",
                        name="check_users_forename_length"),
        CheckConstraint("length(last_name) <= 50",
                        name="check_users_surname_length"),
        CheckConstraint(
            "mfa_enabled = false OR mfa_secret IS NOT NULL",
            name="check_users_mfa_secret",
        ),
        CheckConstraint("failed_logins >= 0",
                        name="check_users_failed_logins"),
        # usernames and emails must be unique regardless of caps
        Index("unique_users_username", text("lower(username)"), unique=True),
        Index("unique_users_email", text("lower(email)"), unique=True),
    )

    # user attributes
    user_id = db.Column(Integer, primary_key=True, autoincrement=True)
    role_id = db.Column(
        Integer, ForeignKey("roles.role_id", ondelete="RESTRICT"), nullable=False
    )
    first_name = db.Column(String(50), nullable=False)
    last_name = db.Column(String(50), nullable=False)
    username = db.Column(String(255), nullable=False, unique=True)
    email = db.Column(String(255), nullable=False, unique=True)
    password_hash = db.Column(String, nullable=False)
    mfa_enabled = db.Column(
        db.Boolean, nullable=False, default=False, server_default=false()
    )
    mfa_secret = db.Column(String, nullable=True)
    failed_logins = db.Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=true()
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    password_changed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    # identify current sessions user
    def get_id(self) -> str:
        return str(self.user_id)


# inventory
class InventoryItem(db.Model):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("price >= 0 AND price <= 100000",
                        name="check_inventory_price"),
        CheckConstraint(
            "quantity >= 0 AND quantity <= 1000000", name="check_inventory_quantity"
        ),
        CheckConstraint(
            "reorder_level >= 0 AND reorder_level <= 1000000",
            name="check_inventory_reorder",
        ),
    )

    # inventory item attributes
    item_id = db.Column(Integer, primary_key=True, autoincrement=True)
    sku = db.Column(String(100), nullable=False, unique=True)
    name = db.Column(String(255), nullable=False)
    description = db.Column(String, nullable=True)
    price = db.Column(Numeric(10, 2), nullable=False)
    quantity = db.Column(Integer, nullable=False,
                         default=0, server_default=text("0"))
    reorder_level = db.Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=true()
    )


# customers
class Customer(db.Model):
    __tablename__ = "customers"

    # customer attributes
    customer_id = db.Column(Integer, primary_key=True, autoincrement=True)
    name = db.Column(String(255), nullable=False)
    email = db.Column(String(255), nullable=False, unique=True)
    phone = db.Column(String(50), nullable=True)
    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=true()
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )


# sales
class Sale(db.Model):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint(
            "total >= 0 AND total <= 9999999999.99", name="check_sales_total"
        ),
        # stop repeated form posts creating a second sale
        UniqueConstraint("user_id", "submission_token",
                         name="unique_sales_user"),
    )

    # sale attributes
    sale_id = db.Column(Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    customer_id = db.Column(
        Integer, ForeignKey("customers.customer_id", ondelete="SET NULL"), nullable=True
    )
    sale_date = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    total = db.Column(Numeric(12, 2), nullable=False)
    submission_token = db.Column(String(32), nullable=True)


# sale items
class SaleItem(db.Model):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 1 AND quantity <= 10000", name="check_sale_items_quantity"
        ),
        CheckConstraint(
            "unit_price >= 0 AND unit_price <= 100000",
            name="check_sale_items_unit_price",
        ),
    )

    # sale item attributes
    sale_item_id = db.Column(Integer, primary_key=True, autoincrement=True)
    sale_id = db.Column(
        Integer, ForeignKey("sales.sale_id", ondelete="CASCADE"), nullable=False
    )
    item_id = db.Column(
        Integer, ForeignKey("inventory.item_id", ondelete="RESTRICT"), nullable=False
    )
    quantity = db.Column(Integer, nullable=False)
    unit_price = db.Column(Numeric(10, 2), nullable=False)


# logs
class Log(db.Model):
    __tablename__ = "logs"
    __table_args__ = (
        # an id cannot be recorded without its type paired to it
        CheckConstraint(
            "entity_id IS NULL OR entity_type IS NOT NULL",
            name="check_log_id_with_type",
        ),
        CheckConstraint(
            "entity_type IS NULL OR entity_type IN ('USER', 'CUSTOMER', 'INVENTORY', 'SALE', 'DELETION_REQUEST')",
            name="check_log_type",
        ),
    )

    # log attributes
    log_id = db.Column(Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    action = db.Column(String(100), nullable=False)
    entity_type = db.Column(String(30), nullable=True)
    entity_id = db.Column(Integer, nullable=True)
    logged_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )


# deletion_requests
class DeletionRequest(db.Model):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('USER', 'CUSTOMER', 'INVENTORY')",
            name="check_deletion_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="check_deletion_status",
        ),
        CheckConstraint(
            "status = 'PENDING' OR (reviewed_by IS NOT NULL AND resolved_at IS NOT NULL)",
            name="check_deletion_review_status",
        ),
        # allow one pending request
        Index(
            "unique_deletion_pending_target",
            "entity_type",
            "entity_id",
            unique=True,
            sqlite_where=text("status = 'PENDING'"),
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    # deletion_request attributes
    request_id = db.Column(Integer, primary_key=True, autoincrement=True)
    requested_by = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    entity_type = db.Column(String(20), nullable=False)
    entity_id = db.Column(Integer, nullable=False)
    status = db.Column(
        String(10), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)


# password reset tokens
class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"
    # two rows can't store the same hash
    __table_args__ = (
        UniqueConstraint("token_hash", name="unique_password_reset_hash"),
    )

    # password reset token attributes
    token_id = db.Column(Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash = db.Column(String(64), nullable=True)
    requested_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    approved_by = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)


# customer change requests
class CustomerChangeRequest(db.Model):
    __tablename__ = "customer_change_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="check_customer_change_status",
        ),
        CheckConstraint(
            "status = 'PENDING' OR (reviewed_by IS NOT NULL AND resolved_at IS NOT NULL)",
            name="check_customer_change_review_status",
        ),
        # allow one pending change
        Index(
            "unique_customer_change_requests_pending_customer",
            "customer_id",
            unique=True,
            sqlite_where=text("status = 'PENDING'"),
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    # customer change request atrributes
    request_id = db.Column(Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(
        Integer,
        ForeignKey("customers.customer_id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by = db.Column(
        Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    requested_name = db.Column(String(255), nullable=False)
    requested_email = db.Column(String(255), nullable=False)
    requested_phone = db.Column(String(50), nullable=True)
    status = db.Column(
        String(10), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
