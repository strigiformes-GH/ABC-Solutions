# implement the app's main features


from __future__ import annotations  # flexible type hints


import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import click


# user sesison imports
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user

# sqlalchemy
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

# internal imports
from database.create_db import db
from models import (
    Customer,
    CustomerChangeRequest,
    DeletionRequest,
    InventoryItem,
    Log,
    PasswordResetToken,
    Role,
    Sale,
    SaleItem,
    User,
    utc_now,
)
from services.auth import password_hasher, role_required
from services.validation import (
    is_valid_email,
    is_valid_password,
    is_valid_person_name,
    is_valid_phone,
    is_valid_username,
)

# group main feature pages together
features = Blueprint("features", __name__)


# find the user's role
def role_name(user: User) -> str:
    role = db.session.get(Role, user.role_id)
    return role.name if role else ""


# add a log to db transaction (to be saved later)
def log(
    action: str, entity_type: str | None = None, entity_id: int | None = None
) -> None:
    db.session.add(
        Log(
            user_id=current_user.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    )


def item_status(item: InventoryItem) -> str:
    if item.quantity == 0:
        return "Out of stock"
    if item.quantity <= item.reorder_level:
        return "Low stock"
    return "In stock"


def customer_form_values() -> tuple[str, str, str]:
    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    if not is_valid_person_name(first, 125) or not is_valid_person_name(last, 125):
        abort(400)
    if not is_valid_email(email):
        abort(400)
    if not is_valid_phone(phone):
        abort(400)
    return f"{first} {last}", email, phone


def handle_deletion_request(
    row: DeletionRequest, reviewer_id: int, approved: bool
) -> None:
    if row.status != "PENDING":  # only review pending requests
        abort(409)
    row.status = "APPROVED" if approved else "REJECTED"
    row.reviewed_by = reviewer_id
    row.resolved_at = utc_now()
    if approved:
        # deactivate the record
        if row.entity_type == "INVENTORY":
            target = db.session.get(InventoryItem, row.entity_id)
            if target:
                target.is_active = False
        elif row.entity_type == "CUSTOMER":
            target_customer = db.session.get(Customer, row.entity_id)
            if target_customer:
                target_customer.is_active = False
        elif row.entity_type == "USER":
            target_user = db.session.get(User, row.entity_id)
            if target_user:
                target_user.is_active = False
    log(
        "DELETION_APPROVED" if approved else "DELETION_REJECTED",
        row.entity_type,
        row.entity_id,
    )
    db.session.commit()


@features.post("/inventory/save")
@role_required("Admin", "Manager", "Employee")
def inventory_save() -> str:
    # try to load supplied item id
    raw_id = request.form.get("item_id", "")
    item = db.session.get(InventoryItem, int(
        raw_id)) if raw_id.isdigit() else None
    # id must be an active item
    if raw_id and (item is None or not item.is_active):
        abort(404)
    sku = request.form.get("sku", "").strip()
    name = request.form.get("name", "").strip()
    if not sku or len(sku) > 100 or not name or len(name) > 255:
        abort(400)
    # convert from text to numbers
    try:
        price = Decimal(request.form.get("price", ""))
        quantity = int(request.form.get("quantity", ""))
        reorder_level = int(request.form.get("reorder_level", "0"))
    except (InvalidOperation, ValueError):
        abort(400)
    # reject invalid amounts
    if not price.is_finite() or price < 0 or price > Decimal("100000"):
        abort(400)
    if not 0 <= quantity <= 1_000_000 or not 0 <= reorder_level <= 1_000_000:
        abort(400)
    # employees can edit details, but not stock levels
    if role_name(current_user) == "Employee":
        if item is None and (quantity != 0 or reorder_level != 0):
            abort(403)
        if item is not None and (
            quantity != item.quantity or reorder_level != item.reorder_level
        ):
            abort(403)
    # new item or updated item
    created = item is None
    item = item or InventoryItem()
    # item details
    item.sku = sku
    item.name = name
    item.description = request.form.get("description", "").strip() or None
    item.price = price
    item.quantity = quantity
    item.reorder_level = reorder_level
    item.is_active = True
    # send to db
    db.session.add(item)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        flash("Stock code in use.", "error")
        return redirect(url_for("app_inventory"))
    # use new/updated decider for log
    log(
        "INVENTORY_CREATED" if created else "INVENTORY_UPDATED",
        "INVENTORY",
        item.item_id,
    )
    db.session.commit()
    return redirect(url_for("app_inventory"))


@features.post("/inventory/<int:item_id>/delete")
@role_required("Admin", "Manager", "Employee")
def inventory_delete(item_id: int) -> str:
    item = db.session.get(InventoryItem, item_id)
    if not item or not item.is_active:
        abort(404)  # no item or already archived
    pending = db.session.scalar(  # already requested?
        select(DeletionRequest.request_id).where(
            DeletionRequest.entity_type == "INVENTORY",
            DeletionRequest.entity_id == item_id,
            DeletionRequest.status == "PENDING",
        )
    )
    if pending:
        abort(409, description="Archive request already exists.")
    if role_name(current_user) == "Employee":
        # employees have to request
        db.session.add(
            DeletionRequest(
                requested_by=current_user.user_id,
                entity_type="INVENTORY",
                entity_id=item_id,
            )
        )
        action = "DELETION_REQUESTED"
    else:
        # admins/managers can archive the item
        item.is_active = False
        action = "INVENTORY_ARCHIVED"
    log(action, "INVENTORY", item_id)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409)
    flash(
        (
            "Deletion request submitted."
            if action == "DELETION_REQUESTED"
            else "Inventory item archived."
        ),
        "success",
    )
    return redirect(url_for("app_inventory"))


@features.post("/customers/save")
@role_required("Admin", "Manager", "Employee")
def customer_save() -> str:
    # empty id is create, number id is edit
    raw_id = request.form.get("customer_id", "")
    customer = db.session.get(Customer, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (customer is None or not customer.is_active):
        abort(404)
    # employees can add customers, but not edit without requesting
    if customer and role_name(current_user) not in {"Admin", "Manager"}:
        abort(403)
    name, email, phone = customer_form_values()
    # after validating, use record or create new customer
    customer = customer or Customer()
    customer.name, customer.email, customer.phone, customer.is_active = (
        name,
        email,
        phone or None,
        True,
    )
    db.session.add(customer)
    # send to db
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        flash("Unable to save details.", "error")
        return redirect(url_for("app_customers"))
    action = "CUSTOMER_UPDATED" if raw_id else "CUSTOMER_CREATED"
    log(action, "CUSTOMER", customer.customer_id)
    db.session.commit()
    return redirect(url_for("app_customers"))


@features.post("/customers/<int:customer_id>/delete")
@role_required("Admin", "Manager", "Employee")
def customer_delete(customer_id: int) -> str:
    customer = db.session.get(Customer, customer_id)
    if not customer or not customer.is_active:
        abort(404)
    # only one request pending at a time
    pending = db.session.scalar(
        select(DeletionRequest.request_id).where(
            DeletionRequest.entity_type == "CUSTOMER",
            DeletionRequest.entity_id == customer_id,
            DeletionRequest.status == "PENDING",
        )
    )
    if pending:
        abort(409, description="A request already exists for this customer.")
    if role_name(current_user) == "Employee":
        # request deletion
        db.session.add(
            DeletionRequest(
                requested_by=current_user.user_id,
                entity_type="CUSTOMER",
                entity_id=customer_id,
            )
        )
        log("DELETION_REQUESTED", "CUSTOMER", customer_id)
    else:
        # archive directly
        customer.is_active = False
        log("CUSTOMER_ARCHIVED", "CUSTOMER", customer_id)
    # send to db
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409)
    return redirect(url_for("app_customers"))


# employee requests
@features.post("/customers/<int:customer_id>/edit-request")
@role_required("Employee")
def customer_edit_request(customer_id: int) -> str:
    customer = db.session.get(Customer, customer_id)
    if not customer or not customer.is_active:
        abort(404)
    # prevent multiple requests
    existing = db.session.scalar(
        select(CustomerChangeRequest).where(
            CustomerChangeRequest.customer_id == customer_id,
            CustomerChangeRequest.status == "PENDING",
        )
    )
    if existing:
        flash("A request is pending.", "error")
        return redirect(url_for("app_customer_activity", customer_id=customer_id))
    name, email, phone = customer_form_values()
    # after validating, ensure atleast one detail is changed
    if not any(
        (
            name != customer.name,
            email != customer.email,
            phone != (customer.phone or ""),
        )
    ):
        abort(400)
    # save details to a request (do not change record until approved)
    change = CustomerChangeRequest(
        customer_id=customer_id,
        requested_by=current_user.user_id,
        requested_name=name,
        requested_email=email,
        requested_phone=phone or None,
    )
    # send to db
    db.session.add(change)
    log("CUSTOMER_EDIT_REQUESTED", "CUSTOMER", customer_id)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A request is pending.", "error")
        return redirect(url_for("app_customer_activity", customer_id=customer_id))
    flash("Request sent for review.", "success")
    return redirect(url_for("app_customer_activity", customer_id=customer_id))


# review requests
@features.post("/approvals/customer-edit/<int:request_id>/<decision>")
@role_required("Admin", "Manager")
def customer_edit_approval(request_id: int, decision: str) -> str:
    if decision not in {"approve", "reject"}:
        abort(404)
    change = db.session.get(CustomerChangeRequest, request_id)
    if not change:
        abort(404)
    if change.status != "PENDING":  # only review once
        abort(409)
    customer = db.session.get(Customer, change.customer_id)
    if not customer:
        abort(404)
    now = utc_now()
    if decision == "approve":
        # apply changes
        customer.name = change.requested_name
        customer.email = change.requested_email
        customer.phone = change.requested_phone
        change.status = "APPROVED"
        action = "CUSTOMER_EDIT_APPROVED"
    else:
        # reject changes
        change.status = "REJECTED"
        action = "CUSTOMER_EDIT_REJECTED"
    change.reviewed_by = current_user.user_id
    change.resolved_at = now
    log(action, "CUSTOMER", customer.customer_id)
    # send to db
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Email is in use.", "error")
    return redirect(url_for("app_approvals"))


SALE_TOTAL_LIMIT = Decimal("9999999999.99")


def sale_info_to_dictionary() -> dict[int, int]:
    item_ids = request.form.getlist("item_id")
    quantities = request.form.getlist("quantity")
    # every item has a quantity
    if len(item_ids) != len(quantities):
        abort(400)
    wanted: dict[int, int] = {}
    for raw_item, raw_quantity in zip(item_ids, quantities):
        raw_item, raw_quantity = raw_item.strip(), raw_quantity.strip()
        # ignore blanks
        if not raw_item and not raw_quantity:
            continue
        # ascii only
        if not (
            raw_item.isascii()
            and raw_item.isdigit()
            and raw_quantity.isascii()
            and raw_quantity.isdigit()
        ):
            abort(400)
        # text to numbers
        item_id, quantity = int(raw_item), int(raw_quantity)
        if not 1 <= quantity <= 10_000 or wanted.get(item_id, 0) + quantity > 10_000:
            abort(400)
        # add quantity to total for the item
        wanted[item_id] = wanted.get(item_id, 0) + quantity
    return wanted


# recognise repeated sales from a user
def existing_sale(token: str) -> Sale | None:
    return db.session.scalar(
        select(Sale).where(
            Sale.user_id == current_user.user_id, Sale.submission_token == token
        )
    )


def already_recorded(sale: Sale) -> str:
    flash("Sale already recorded.", "success")
    return redirect(url_for("features.sale_receipt", sale_id=sale.sale_id))


@features.post("/sales/create")
@role_required("Admin", "Manager", "Employee")
def sale_create() -> str:
    # check token format
    token = request.form.get("submission_token", "")
    if len(token) != 32 or any(
        character not in "0123456789abcdef" for character in token
    ):
        abort(400)
    wanted = sale_info_to_dictionary()
    # customer is optional, but must be active
    customer_id_value = request.form.get("customer_id", "")
    if customer_id_value and not (
        customer_id_value.isascii() and customer_id_value.isdigit()
    ):
        abort(400)
    customer_id = int(customer_id_value) if customer_id_value else None
    if customer_id is not None:
        customer = db.session.get(Customer, customer_id)
        if not customer or not customer.is_active:
            abort(400)
    # don't save sales with no items in
    if not wanted:
        flash("Add at least one item and quantity.", "error")
        return redirect(url_for("app_sale_new"))

    # save inputs to restore if unavailable
    def keep_form_inputs() -> None:
        session["sale_form_memory"] = {
            "customer_id": customer_id_value,
            "item_ids": request.form.getlist("item_id"),
            "quantities": request.form.getlist("quantity"),
        }

    # if form submitted, return sale
    previous = existing_sale(token)
    if previous:
        return already_recorded(previous)
    # lock row order and refresh them
    # prevent simultaneous sales overselling stock
    items = {
        item.item_id: item
        for item in db.session.scalars(
            select(InventoryItem)
            .where(InventoryItem.item_id.in_(sorted(wanted)))
            .order_by(InventoryItem.item_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    # recheck after locks
    # request may have completed while this one was waiting
    previous = existing_sale(token)
    if previous:
        db.session.rollback()
        return already_recorded(previous)
    total = Decimal("0.00")
    # check all items are valid and calculate total
    for item_id, quantity in wanted.items():
        item = items.get(item_id)
        if not item or not item.is_active or item.quantity < quantity:
            keep_form_inputs()
            db.session.rollback()
            flash("Insufficient stock or item unavailable.", "error")
            return redirect(url_for("app_sale_new"))
        total += item.price * quantity
    if total > SALE_TOTAL_LIMIT:
        db.session.rollback()
        flash("Total too large.", "error")
        return redirect(url_for("app_sale_new"))
    # create the sale
    sale = Sale(
        user_id=current_user.user_id,
        customer_id=customer_id,
        total=total,
        submission_token=token,
    )
    db.session.add(sale)
    # send to db
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        previous = existing_sale(token)  # return identical request sale
        if previous:
            return already_recorded(previous)
        abort(409)
    # adjust stock
    for item_id, quantity in wanted.items():
        item = items[item_id]
        item.quantity -= quantity
        db.session.add(
            SaleItem(
                sale_id=sale.sale_id,
                item_id=item_id,
                quantity=quantity,
                unit_price=item.price,
            )
        )
    log("SALE_RECORDED", "SALE", sale.sale_id)
    db.session.commit()
    # send receipt
    return redirect(url_for("features.sale_receipt", sale_id=sale.sale_id))


# account create
@features.post("/admin/users/create")
@role_required("Admin")
def admin_user_create() -> str:
    role = db.session.scalar(select(Role).where(
        Role.name == request.form.get("role")))
    password = request.form.get("password", "")
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    if (
        not role
        or not is_valid_person_name(first_name)
        or not is_valid_person_name(last_name)
    ):
        abort(400)
    if (
        not is_valid_username(username)
        or not is_valid_email(email)
        or not is_valid_password(password)
    ):
        abort(400)
    # create account and store hash
    user = User(
        first_name=first_name,
        last_name=last_name,
        username=username,
        email=email,
        role_id=role.role_id,
        password_hash=password_hasher.hash(password),
        is_active=True,
    )
    db.session.add(user)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        flash("Unable to create.", "error")
        return redirect(url_for("app_user_create"))
    log("USER_REGISTERED", "USER", user.user_id)
    db.session.commit()
    return redirect(url_for("app_users"))


# account update
@features.post("/admin/users/<int:user_id>/update")
@role_required("Admin")
def admin_user_update(user_id: int) -> str:
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    # cannot change their own role
    if user.user_id == current_user.user_id and request.form.get("role") != role_name(
        user
    ):
        abort(403)
    # submitted role must match a db role
    selected_role = db.session.scalar(
        select(Role).where(Role.name == request.form.get("role"))
    )
    if selected_role is None:
        abort(400)
    changed = selected_role.role_id != user.role_id
    user.role_id = selected_role.role_id
    if changed:
        log("ROLE_CHANGED", "USER", user.user_id)
    db.session.commit()
    return redirect(url_for("app_users"))


# account reactivation
@features.post("/admin/users/<int:user_id>/activate")
@role_required("Admin", "Manager")
def activate_user(user_id: int) -> str:
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    requester_role = role_name(current_user)
    target_role = role_name(user)
    # managers can activate employees only
    if requester_role == "Manager" and target_role != "Employee":
        abort(403)
    user.is_active = True
    log("USER_ACTIVATED", "USER", user.user_id)
    db.session.commit()
    return redirect(url_for("app_user_requests"))


# account deactivation
@features.post("/admin/users/<int:user_id>/deactivate")
@role_required("Admin", "Manager")
def deactivate_user(user_id: int) -> str:
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    requester_role, target_role = role_name(current_user), role_name(user)
    # cannot deactivate own account
    if user.user_id == current_user.user_id:
        abort(403)
    # managers can deactivate employees
    if requester_role == "Manager" and target_role != "Employee":
        abort(403)
    if target_role == "Admin":
        active_admins = db.session.scalar(
            select(func.count())
            .select_from(User)
            .join(Role)
            .where(Role.name == "Admin", User.is_active.is_(True))
        )
        if active_admins <= 1:  # don't deactivate the last admin
            abort(409)
    # manager requests go to admins
    if requester_role == "Manager":
        db.session.add(
            DeletionRequest(
                requested_by=current_user.user_id,
                entity_type="USER",
                entity_id=user.user_id,
            )
        )
        action = "DELETION_REQUESTED"
    else:
        user.is_active = False
        action = "USER_DEACTIVATED"
    log(action, "USER", user.user_id)
    # send to db
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409)
    return redirect(url_for("app_users"))


@features.post("/approvals/deletion/<int:request_id>/<decision>")
@role_required("Admin", "Manager")
def deletion_approval(request_id: int, decision: str) -> str:
    if decision not in {"approve", "reject"}:
        abort(404)
    row = db.session.get(DeletionRequest, request_id)
    if not row:
        abort(404)
    # only admins review user deactivations
    if row.entity_type == "USER" and role_name(current_user) != "Admin":
        abort(403)
    # apply deletion
    handle_deletion_request(row, current_user.user_id, decision == "approve")
    return redirect(url_for("app_approvals"))


@features.post("/approvals/password-reset/<int:request_id>/<decision>")
@role_required("Admin", "Manager")
def password_reset_approval(request_id: int, decision: str) -> str:
    if decision not in {"approve", "reject"}:
        abort(404)
    reset = db.session.get(PasswordResetToken, request_id)
    # must be currently awaiting approval
    if not reset or reset.token_hash is not None or reset.used_at is not None:
        abort(404)
    user = db.session.get(User, reset.user_id)
    if not user:
        abort(404)
    # cannot approve own request
    if user.user_id == current_user.user_id:
        abort(403)
    target_role = role_name(user)
    if role_name(current_user) == "Manager" and target_role != "Employee":
        abort(403)
    if decision == "reject":  # remove request and return to approvals
        db.session.delete(reset)
        db.session.commit()
        return redirect(url_for("app_approvals"))

    now = utc_now()
    # mark older links as used/expired
    outstanding = db.session.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.user_id,
            PasswordResetToken.token_hash.is_not(None),
            PasswordResetToken.used_at.is_(None),
        )
    ).all()
    for previous in outstanding:
        previous.used_at = now
    # generate token, but store hash
    token = secrets.token_urlsafe(32)
    reset.token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    reset.approved_by = current_user.user_id
    reset.expires_at = now + timedelta(minutes=30)
    log("PASSWORD_RESET_APPROVED", "USER", user.user_id)
    db.session.commit()
    return render_template(
        "auth/reset_link.html",
        page_title="Password reset link",
        reset_url=url_for("auth.set_password", token=token),
        target_username=user.username,
    )


@features.get("/sales/<int:sale_id>/receipt")
@role_required("Admin", "Manager", "Employee")
def sale_receipt(sale_id: int) -> str:
    sale = db.session.get(Sale, sale_id)
    if not sale:
        abort(404)
    # employees can't view other staff's sales
    if role_name(current_user) == "Employee" and sale.user_id != current_user.user_id:
        abort(404)
    # get sale and item info
    sale_lines = db.session.execute(
        select(SaleItem, InventoryItem)
        .join(InventoryItem, InventoryItem.item_id == SaleItem.item_id)
        .where(SaleItem.sale_id == sale_id)
    ).all()
    # pass receipt details to template
    return render_template(
        "sales/receipt.html",
        page_title="Sale receipt",
        sale={
            "id": sale.sale_id,
            "total": f"{sale.total:.2f}",
            "date": sale.sale_date.strftime("%d %b %Y, %H:%M"),
            "customer": (
                db.session.get(Customer, sale.customer_id).name
                if sale.customer_id
                else "Walk-in"
            ),
            "employee": db.session.get(User, sale.user_id).first_name,
            "sale_lines": [
                {
                    "name": item.name,
                    "quantity": line.quantity,
                    "unit_price": f"{line.unit_price:.2f}",
                    "total": f"{line.unit_price * line.quantity:.2f}",
                }
                for line, item in sale_lines
            ],
        },
    )


# flask command to anonymise customer (GDPR)
@features.cli.command("anonymise-customer")
@click.argument("customer_id", type=int)
def anonymise_customer(customer_id: int) -> None:
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        raise click.ClickException("Customer not found.")
    # replace details and deactivate
    customer.name = "Anonymised customer"
    customer.email = f"anonymised-{customer.customer_id}@invalid.example"
    customer.phone = None
    customer.is_active = False
    # remove info from pending requests
    for change in db.session.scalars(
        select(CustomerChangeRequest).where(
            CustomerChangeRequest.customer_id == customer_id
        )
    ):
        change.requested_name = "Anonymised customer"
        change.requested_email = (
            f"anonymised-{customer.customer_id}-{change.request_id}@invalid.example"
        )
        change.requested_phone = None
    # log and save changes
    db.session.add(
        Log(
            user_id=None,
            action="CUSTOMER_ANONYMISED",
            entity_type="CUSTOMER",
            entity_id=customer_id,
        )
    )
    db.session.commit()
    click.echo(f"Customer {customer_id} anonymised.")


# flask command to clear log history
@features.cli.command("purge-logs")
@click.option(
    "--older-than-days", type=click.IntRange(min=30), default=365, show_default=True
)
def purge_logs(older_than_days: int) -> None:
    """Delete logs older than the retention period (default 365 days)."""
    # calculate the cutoff date
    cutoff = utc_now() - timedelta(days=older_than_days)
    removed = db.session.execute(
        delete(Log).where(Log.logged_at < cutoff)).rowcount
    # add log for purge
    db.session.add(
        Log(
            user_id=None,
            action="LOGS_PURGED",
            entity_type=None,
            entity_id=None,
        )
    )
    db.session.commit()
    click.echo(f"Removed {removed} logs older than {older_than_days} days.")
