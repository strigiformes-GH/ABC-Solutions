# create the app and connect everything


import secrets
from datetime import UTC, datetime, timedelta
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func, select
from audit_labels import audit_action_label
from config import Config, validate_production
from database.create_db import create_db, db
from models import Customer, CustomerChangeRequest, DeletionRequest, InventoryItem, Log, PasswordResetToken, Role, Sale, User
from services.auth import auth, login_manager, pending_mfa_user
from services.features import features
from services.reporting import customer_metrics, inventory_status_summary
from services.security import csrf_token, validate_csrf


app: Flask = Flask(__name__)
app.config.from_object(Config)
validate_production(app.config)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    minutes=30)  # expire sessions after 30 mins
# stop startup if the app has no key
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Set SECRET_KEY in the config.")


# connect the db, register roots
create_db(app)
login_manager.init_app(app)
app.register_blueprint(auth)
app.register_blueprint(features)


@app.before_request
def enforce_security_boundaries() -> None:
    if request.method == "POST":
        validate_csrf()  # require a token for submission
    pending_user = pending_mfa_user()
    if pending_user is not None:
        # mfa until setup/verification finishes
        allowed = {"auth.mfa_setup", "auth.mfa_verify",
                   "auth.pending_logout", "static"}
        if request.endpoint not in allowed:
            target = "auth.mfa_setup" if not pending_user.mfa_enabled else "auth.mfa_verify"
            return redirect(url_for(target))
    if request.endpoint and request.endpoint.startswith("app_"):
        # check protected screens
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        permitted_roles = APP_SCREEN_ROLES.get(request.endpoint, set())
        actual_role = db.session.get(Role, current_user.role_id)
        if not actual_role or actual_role.name not in permitted_roles:
            abort(403)
    return None


def _seed_roles() -> None:
    for role_name in ("Admin", "Manager", "Business", "Employee"):
        if db.session.query(Role).filter_by(name=role_name).one_or_none() is None:
            db.session.add(Role(name=role_name))
    db.session.commit()
    print("Default roles are ready.")


@app.cli.command("init-db")
def init_db() -> None:
    # create the tables and add roles
    if app.config["APP_ENV"] == "production":
        raise RuntimeError("Use alembic upgrade head and flask --app app seed-roles in production.")
    db.create_all()
    _seed_roles()


@app.cli.command("seed-roles")
def seed_roles() -> None:
    _seed_roles()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if app.config["APP_ENV"] == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if current_user.is_authenticated or pending_mfa_user() is not None:
        response.headers["Cache-Control"] = "no-store"
    return response


APP_ROLES = ("Admin", "Manager", "Business", "Employee")
ALL_ROLES = set(APP_ROLES)
ADMIN_MANAGER_ROLES = {"Admin", "Manager"}
OPERATIONAL_ROLES = {"Admin", "Manager", "Employee"}


# only show links that match the user's role
APP_NAVIGATION = [
    {"label": "Inventory", "endpoint": "app_inventory", "roles": ALL_ROLES},
    {"label": "Customers", "endpoint": "app_customers", "roles": OPERATIONAL_ROLES},
    {"label": "New sale", "endpoint": "app_sale_new", "roles": OPERATIONAL_ROLES},
    {"label": "Sales history", "endpoint": "app_sales_history",
        "roles": ADMIN_MANAGER_ROLES},
    {"label": "Reports", "endpoint": "app_reports",
        "roles": ADMIN_MANAGER_ROLES | {"Business"}},
    {"label": "Users", "endpoint": "app_users", "roles": ADMIN_MANAGER_ROLES},
    {"label": "Approvals", "endpoint": "app_approvals", "roles": ADMIN_MANAGER_ROLES},
    {"label": "Logs", "endpoint": "app_logs", "roles": {"Admin"}},
]


# protect each screen with its allowed roles
APP_SCREEN_ROLES = {
    "app_inventory": ALL_ROLES,
    "app_inventory_edit": OPERATIONAL_ROLES,
    "app_inventory_archive": OPERATIONAL_ROLES,
    "app_customers": OPERATIONAL_ROLES,
    "app_customer_activity": OPERATIONAL_ROLES,
    "app_customer_edit": ADMIN_MANAGER_ROLES,
    "app_customer_edit_request": {"Employee"},
    "app_customer_delete": OPERATIONAL_ROLES,
    "app_sale_new": OPERATIONAL_ROLES,
    "app_sales_history": ADMIN_MANAGER_ROLES,
    "app_sale_exceptions": OPERATIONAL_ROLES,
    "app_reports": ADMIN_MANAGER_ROLES | {"Business"},
    "app_inventory_report": ADMIN_MANAGER_ROLES | {"Business"},
    "app_customer_report": ADMIN_MANAGER_ROLES | {"Business"},
    "app_report_states": ADMIN_MANAGER_ROLES | {"Business"},
    "app_users": ADMIN_MANAGER_ROLES,
    "app_user_requests": ADMIN_MANAGER_ROLES,
    "app_user_create": {"Admin"},
    "app_user_edit": {"Admin"},
    "app_user_deactivate": ADMIN_MANAGER_ROLES,
    "app_approvals": ADMIN_MANAGER_ROLES,
    "app_logs": {"Admin"},
    "app_log_detail": {"Admin"},
}


def report_date_bounds() -> tuple[datetime | None, datetime | None]:
    # validate dates
    start_text = request.args.get("from_date", "")
    end_text = request.args.get("to_date", "")
    try:
        start = datetime.fromisoformat(start_text).replace(
            tzinfo=UTC) if start_text else None
        # add a day so the selected end date is included
        end = datetime.fromisoformat(end_text).replace(
            tzinfo=UTC) + timedelta(days=1) if end_text else None
    except ValueError:
        abort(400)
    if start and end and start >= end:
        abort(400)
    return start, end


def current_user_role() -> str:
    if current_user.is_authenticated:
        role = db.session.get(Role, current_user.role_id)
        if role:
            return role.name
    return "Unknown"  # admin return issue


@app.get("/healthz")
def healthz() -> object:
    db.session.scalar(select(1))
    return jsonify(status="ok")  # check db repsonses


@app.errorhandler(400)
def bad_request(_error: object) -> tuple[str, int]:
    # keep error pages consistent
    return render_template("errors/error.html", page_title="Bad request", message="The request could not be completed."), 400


@app.errorhandler(403)
def forbidden(_error: object) -> tuple[str, int]:
    return render_template("errors/error.html", page_title="Access denied", message="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_error: object) -> tuple[str, int]:
    return render_template("errors/error.html", page_title="Page not found", message="The requested page could not be found."), 404


@app.errorhandler(409)
def conflict(error: object) -> tuple[str, int]:
    # duplicate customer requests
    message = getattr(error, "description",
                      "This record already has a pending request.")
    if message == "A request already exists for this customer.":
        message = "An archive request already exists for this customer."
    return render_template("errors/error.html", page_title="Request conflict", message=message), 409


@app.errorhandler(429)
def too_many_requests(_error: object) -> tuple[str, int]:
    return render_template("errors/error.html", page_title="Too many requests", message="Too many requests."), 429


@app.errorhandler(500)
def server_error(_error: object) -> tuple[str, int]:
    # clear failed db work
    db.session.rollback()
    return render_template("errors/error.html", page_title="Server error", message="The request could not be completed."), 500


@app.context_processor
def app_context() -> dict[str, object]:
    # make helpers available to templates
    authenticated = current_user.is_authenticated
    role = db.session.get(
        Role, current_user.role_id) if authenticated else None
    user_role = role.name if role else current_user_role()
    return {
        "app_navigation": [
            item for item in APP_NAVIGATION if user_role in item["roles"]
        ] if authenticated else [],
        "user_role": user_role,
        "show_sign_out": authenticated,
        "pending_mfa": pending_mfa_user() is not None,
        "audit_action_label": audit_action_label,
        "csrf_token": csrf_token,
    }


@app.get("/")
def home() -> object:
    # send signed-in users to the app and others to sign in
    if current_user.is_authenticated:
        return redirect(url_for("app_inventory"))
    return redirect(url_for("auth.login"))


@app.get("/app/inventory")
def app_inventory() -> str:
    # show active stock
    search = request.args.get("q", "").strip()
    query = select(InventoryItem).where(InventoryItem.is_active.is_(True))
    if search:
        query = query.where(
            (InventoryItem.name.ilike(f"%{search}%"))
            | (InventoryItem.sku.ilike(f"%{search}%"))
        )
    if request.args.get("low") == "1":  # include items at the reorder level
        query = query.where(InventoryItem.quantity <=
                            InventoryItem.reorder_level)
    items = db.session.scalars(query.order_by(InventoryItem.name)).all()
    return render_template(
        "inventory/index.html",
        page_title="Inventory",
        active_nav="Inventory",
        inventory_items=[
            {
                "item_id": item.item_id,
                "sku": item.sku,
                "name": item.name,
                "price": f"{item.price:.2f}",
                "quantity": item.quantity,
                "status": "Out of stock" if item.quantity == 0 else (
                    "Low stock" if item.quantity <= item.reorder_level else "In stock"
                ),
            }
            for item in items
        ],
        search=search,
        low_only=request.args.get("low") == "1",
        can_edit_stock=current_user_role() in {"Admin", "Manager"},
    )


@app.get("/app/inventory/edit")
def app_inventory_edit() -> str:
    raw_id = request.args.get("item_id", "")
    item = db.session.get(InventoryItem, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (item is None or not item.is_active):
        abort(404)
    return render_template(
        "inventory/edit.html",
        page_title="Edit inventory item" if item else "Add inventory item",
        active_nav="Inventory",
        item=item,
        can_edit_stock=current_user_role() in {"Admin", "Manager"},
    )


@app.get("/app/inventory/archive")
def app_inventory_archive() -> str:
    raw_id = request.args.get("item_id", "")
    item = db.session.get(InventoryItem, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (item is None or not item.is_active):
        abort(404)
    if item is None:
        return redirect(url_for("app_inventory"))
    return render_template(
        "inventory/archive.html",
        page_title="Archive or request item removal",
        active_nav="Inventory",
        inventory_item=item,
        user_role=current_user_role(),
    )


@app.get("/app/customers")
def app_customers() -> str:
    # search active customers by name/email
    search = request.args.get("q", "").strip()
    query = select(Customer).where(Customer.is_active.is_(True))
    if search:
        query = query.where(
            Customer.name.ilike(
                f"%{search}%") | Customer.email.ilike(f"%{search}%")
        )
    customers = db.session.scalars(query.order_by(Customer.name)).all()
    return render_template(
        "customers/index.html",
        page_title="Customers",
        active_nav="Customers",
        customers=[
            {
                "customer_id": c.customer_id,
                "name": c.name,
                "first_name": c.name.partition(" ")[0],
                "last_name": c.name.partition(" ")[2],
                "email": c.email,
                "phone": c.phone or "",
            }
            for c in customers
        ],
        search=search,
    )


@app.get("/app/customers/activity")
def app_customer_activity() -> str:
    # show purchase totals/latest sale
    raw_id = request.args.get("customer_id", "")
    customer = db.session.get(Customer, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (customer is None or not customer.is_active):
        abort(404)
    if customer is None:
        customer = db.session.scalar(select(Customer).where(
            Customer.is_active.is_(True)).order_by(Customer.customer_id))
    if customer is None:
        return redirect(url_for("app_customers"))
    purchases = db.session.scalar(select(func.count()).select_from(
        Sale).where(Sale.customer_id == customer.customer_id)) or 0
    lifetime = db.session.scalar(select(func.coalesce(
        func.sum(Sale.total), 0)).where(Sale.customer_id == customer.customer_id))
    last_sale = db.session.scalar(select(func.max(Sale.sale_date)).where(
        Sale.customer_id == customer.customer_id))
    return render_template(
        "customers/activity.html",
        page_title="Customer history and approvals",
        active_nav="Customers",
        customer=customer,
        purchases=purchases,
        lifetime=f"{lifetime:.2f}",
        last_purchase=last_sale.strftime("%d %b %Y") if last_sale else "None",
    )


@app.get("/app/customers/edit")
def app_customer_edit() -> str:
    raw_id = request.args.get("customer_id", "")
    customer = db.session.get(Customer, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (customer is None or not customer.is_active):
        abort(404)
    if customer is None:
        customer = db.session.scalar(select(Customer).where(
            Customer.is_active.is_(True)).order_by(Customer.customer_id))
    if customer is None:
        abort(404)
    customer_data = {
        "customer_id": customer.customer_id,
        "name": customer.name,
        "first_name": customer.name.partition(" ")[0],
        "last_name": customer.name.partition(" ")[2],
        "email": customer.email,
        "phone": customer.phone or "",
    }
    return render_template(
        "customers/edit.html",
        page_title="Edit customer",
        active_nav="Customers",
        customer=customer_data,
    )


@app.get("/app/customers/edit-request")
def app_customer_edit_request() -> str:
    raw_id = request.args.get("customer_id", "")
    customer = db.session.get(Customer, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (customer is None or not customer.is_active):
        abort(404)
    if customer is None:
        customer = db.session.scalar(
            select(Customer).where(Customer.is_active.is_(
                True)).order_by(Customer.customer_id)
        )
    if customer is None:
        abort(404)
    return render_template(
        "customers/edit_request.html",
        page_title="Request a customer edit",
        active_nav="Customers",
        customer={
            "customer_id": customer.customer_id,
            "name": customer.name,
            "first_name": customer.name.partition(" ")[0],
            "last_name": customer.name.partition(" ")[2],
            "email": customer.email,
            "phone": customer.phone or "",
        },
    )


@app.get("/app/customers/delete")
def app_customer_delete() -> str:
    raw_id = request.args.get("customer_id", "")
    customer = db.session.get(Customer, int(
        raw_id)) if raw_id.isdigit() else None
    if raw_id and (customer is None or not customer.is_active):
        abort(404)
    if customer is None:
        customer = db.session.scalar(select(Customer).where(
            Customer.is_active.is_(True)).order_by(Customer.customer_id))
    if customer is None:
        abort(404)
    return render_template(
        "customers/delete.html",
        page_title="Archive or request customer deletion",
        active_nav="Customers",
        customer=customer,
        customer_id=customer.customer_id,
        user_role=current_user_role(),
    )


@app.get("/app/sales/new")
def app_sale_new() -> str:
    # restore form choices after a sale could not be completed
    items = db.session.scalars(
        select(InventoryItem).where(InventoryItem.is_active.is_(
            True)).order_by(InventoryItem.name)
    ).all()
    customers = db.session.scalars(select(Customer).where(
        Customer.is_active.is_(True)).order_by(Customer.name)).all()
    form_state = session.pop("sale_form_memory", {})
    selected_items = form_state.get("item_ids", [])
    selected_quantities = form_state.get("quantities", [])
    line_count = max(1, len(selected_items))
    return render_template(
        "sales/new.html",
        page_title="New sale",
        active_nav="New sale",
        inventory_items=items,
        customers=customers,
        submission_token=secrets.token_hex(16),
        line_rows=range(1, line_count + 1),
        selected_items=selected_items,
        selected_quantities=selected_quantities,
        selected_customer_id=form_state.get("customer_id", ""),
    )


@app.get("/app/sales/history")
def app_sales_history() -> str:
    # filter and sort the latest sales
    query = select(Sale)
    search_id = request.args.get("sale_id", "").strip()
    if search_id:
        if not search_id.isdigit():
            abort(400)
        query = query.where(Sale.sale_id == int(search_id))
    employee_id = request.args.get("employee_id", "")
    if employee_id:
        if not employee_id.isdigit():
            abort(400)
        query = query.where(Sale.user_id == int(employee_id))
    today = datetime.now(UTC).date()
    if request.args.get("range") == "today":
        query = query.where(Sale.sale_date >= datetime.combine(
            today, datetime.min.time(), UTC))
    elif request.args.get("range") == "month":
        month_start = today.replace(day=1)
        query = query.where(Sale.sale_date >= datetime.combine(
            month_start, datetime.min.time(), UTC))
    sort = request.args.get("sort", "newest")
    if sort == "oldest":
        query = query.order_by(Sale.sale_date.asc())
    elif sort == "highest":
        query = query.order_by(Sale.total.desc())
    elif sort == "lowest":
        query = query.order_by(Sale.total.asc())
    else:
        sort = "newest"
        query = query.order_by(Sale.sale_date.desc())
    sales_rows = db.session.scalars(query.limit(200)).all()
    sales = [
        {
            "id": sale.sale_id,
            "date": sale.sale_date.strftime("%d %b %Y, %H:%M"),
            "customer": db.session.get(Customer, sale.customer_id).name if sale.customer_id else "Walk-in",
            "employee": (db.session.get(User, sale.user_id).first_name + " " + db.session.get(User, sale.user_id).last_name),
            "total": f"{sale.total:.2f}",
        }
        for sale in sales_rows
    ]
    return render_template(
        "sales/history.html",
        page_title="Find past sales",
        active_nav="Sales history",
        sales=sales,
        search_id=search_id,
        selected_employee=employee_id,
        selected_range=request.args.get("range", ""),
        selected_sort=sort,
        employees=db.session.scalars(select(User).order_by(
            User.first_name, User.last_name)).all(),
    )


@app.get("/app/sales/exceptions")
def app_sale_exceptions() -> str:
    # display sale outcomes
    return render_template(
        "sales/exceptions.html",
        page_title="Sales completions and exceptions",
        active_nav="Sales history",
    )


def report_filters(start: datetime | None, end: datetime | None) -> list:
    filters = []
    if start:
        filters.append(Sale.sale_date >= start)
    if end:
        filters.append(Sale.sale_date < end)
    return filters


@app.get("/app/reports")
def app_reports() -> str:
    # group sales by date
    start, end = report_date_bounds()
    filters = report_filters(start, end)
    daily = db.session.execute(
        select(func.date(Sale.sale_date), func.count(), func.sum(Sale.total))
        .where(*filters)
        .group_by(func.date(Sale.sale_date))
        .order_by(func.date(Sale.sale_date))
    ).all()
    return render_template(
        "reports/index.html",
        page_title="Reports",
        active_nav="Reports",
        daily_sales=daily,
        from_date=request.args.get("from_date", ""),
        to_date=request.args.get("to_date", ""),
    )


@app.get("/app/reports/inventory")
def app_inventory_report() -> str:
    return render_template(
        "reports/inventory.html",
        page_title="Inventory status report",
        active_nav="Reports",
        inventory=inventory_status_summary(),
    )


@app.get("/app/reports/customers")
def app_customer_report() -> str:
    # pass role to hide from business
    start, end = report_date_bounds()
    metrics = customer_metrics(report_filters(start, end), current_user_role())
    return render_template(
        "reports/customers.html",
        page_title="Customer activity report",
        active_nav="Reports",
        metrics=metrics,
        from_date=request.args.get("from_date", ""),
        to_date=request.args.get("to_date", ""),
    )


@app.get("/app/reports/states")
def app_report_states() -> str:
    return render_template(
        "reports/states.html",
        page_title="Invalid range / No results",
        active_nav="Reports",
    )


def lock_label(user: User) -> str:
    if not user.locked_until:  # account available
        return ""
    until = user.locked_until.replace(
        tzinfo=UTC) if user.locked_until.tzinfo is None else user.locked_until.astimezone(UTC)
    return f"Locked until {until:%H:%M} UTC" if until > datetime.now(UTC) else ""


@app.get("/app/users")
def app_users() -> str:
    rows = db.session.scalars(select(User).order_by(
        User.last_name, User.first_name)).all()
    users = [
        {
            "user_id": user.user_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "email": user.email,
            "role": db.session.get(Role, user.role_id).name,
            "mfa": "Enabled" if user.mfa_enabled else "Not set",
            "status": "Active" if user.is_active else "Inactive",
            "lock": lock_label(user),
        }
        for user in rows
    ]
    return render_template(
        "users/index.html",
        page_title="User management",
        active_nav="Users",
        users=users,
    )


@app.get("/app/users/requests")
def app_user_requests() -> str:
    # show inactive accounts that are waiting for review
    account_rows = db.session.scalars(select(User).where(
        User.is_active.is_(False)).order_by(User.created_at)).all()
    account_requests = [
        {
            "user_id": user.user_id,
            "name": f"{user.first_name} {user.last_name}",
            "role": db.session.get(Role, user.role_id).name,
        }
        for user in account_rows
        if current_user_role() == "Admin" or db.session.get(Role, user.role_id).name == "Employee"
    ]
    return render_template(
        "users/requests.html",
        page_title="Account requests",
        active_nav="Users",
        account_requests=account_requests,
    )


@app.get("/app/users/create")
def app_user_create() -> str:
    return render_template(
        "users/create.html",
        page_title="Create a user",
        active_nav="Users",
    )


@app.get("/app/users/edit")
def app_user_edit() -> str:
    raw_id = request.args.get("user_id", "")
    user = db.session.get(User, int(raw_id)) if raw_id.isdigit() else None
    if raw_id and user is None:
        abort(404)
    if user is None:
        user = current_user
    return render_template(
        "users/edit.html",
        page_title="Edit role or status",
        active_nav="Users",
        user=user,
        roles=db.session.scalars(select(Role).order_by(Role.name)).all(),
    )


@app.get("/app/users/deactivate")
def app_user_deactivate() -> str:
    raw_id = request.args.get("user_id", "")
    user = db.session.get(User, int(raw_id)) if raw_id.isdigit() else None
    if raw_id and user is None:
        abort(404)
    if user is None:
        abort(404)
    return render_template(
        "users/deactivate.html",
        page_title="Deactivate or request user deactivation",
        active_nav="Users",
        user_role=current_user_role(),
        user=user,
        target_role=db.session.get(Role, user.role_id).name,
    )


@app.get("/app/approvals")
def app_approvals() -> str:
    # gather pending requests for approval
    user_role = current_user_role()
    pending_rows = db.session.scalars(
        select(DeletionRequest).where(DeletionRequest.status ==
                                      "PENDING").order_by(DeletionRequest.created_at)
    ).all()
    pending_approvals = []
    for row in pending_rows:
        if row.entity_type == "USER" and user_role != "Admin":
            continue
        if row.entity_type == "USER":
            target = db.session.get(User, row.entity_id)
            label = f"{target.first_name} {target.last_name}" if target else "User"
        elif row.entity_type == "CUSTOMER":
            target = db.session.get(Customer, row.entity_id)
            label = target.name if target else "Customer"
        else:
            target = db.session.get(InventoryItem, row.entity_id)
            label = target.name if target else "Inventory item"
        requester = db.session.get(User, row.requested_by)
        pending_approvals.append({
            "request_id": row.request_id,
            "type": row.entity_type,
            "target": label,
            "requested_by": requester.username if requester else "Unavailable",
            "requested": row.created_at.strftime("%d %b %Y, %H:%M"),
        })
    customer_edit_requests = []
    changes = db.session.scalars(
        select(CustomerChangeRequest)
        .where(CustomerChangeRequest.status == "PENDING")
        .order_by(CustomerChangeRequest.created_at)
    ).all()
    # include only customer fields that changed
    for change in changes:
        customer = db.session.get(Customer, change.customer_id)
        requester = db.session.get(User, change.requested_by)
        if not customer:
            continue
        requested_by = requester.username if requester else "Unavailable"
        for field, current, requested in (
            ("Name", customer.name, change.requested_name),
            ("Email", customer.email, change.requested_email),
            ("Phone", customer.phone or "", change.requested_phone or ""),
        ):
            if current != requested:
                customer_edit_requests.append({
                    "request_id": change.request_id,
                    "customer": customer.name,
                    "field": field,
                    "current": current,
                    "requested": requested,
                    "requested_by": requested_by,
                })
    password_reset_requests = []
    reset_rows = db.session.scalars(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash.is_(None),
            PasswordResetToken.approved_by.is_(None),
            PasswordResetToken.used_at.is_(None),
        )
        .order_by(PasswordResetToken.requested_at)
    ).all()
    # hide the current user's request and restrict manager reviews
    for reset in reset_rows:
        user = db.session.get(User, reset.user_id)
        if (
            not user
            or user.user_id == current_user.user_id
            or (user_role == "Manager" and db.session.get(Role, user.role_id).name != "Employee")
        ):
            continue
        password_reset_requests.append({
            "request_id": reset.token_id,
            "requested_by": user.username,
            "requested": reset.requested_at.strftime("%d %b %Y, %H:%M"),
        })
    return render_template(
        "approvals/index.html",
        page_title="Approvals",
        active_nav="Approvals",
        pending_approvals=pending_approvals,
        customer_edit_requests=customer_edit_requests,
        password_reset_requests=password_reset_requests,
    )


@app.get("/app/logs")
def app_logs() -> str:
    query = select(Log)
    if request.args.get("user_id", "").isdigit():
        query = query.where(Log.user_id == int(request.args["user_id"]))
    if request.args.get("action", "").strip():
        query = query.where(Log.action == request.args["action"].strip())
    logs = db.session.scalars(query.order_by(
        Log.logged_at.desc()).limit(200)).all()
    log_events = [
        {
            "id": str(row.log_id),
            "date": row.logged_at.strftime("%d %b %Y, %H:%M"),
            "actor": f"User #{row.user_id}" if row.user_id else "System",
            "action": row.action,
            "record": f"{row.entity_type} #{row.entity_id}" if row.entity_type and row.entity_id else "None",
            "result": "Recorded",
        }
        for row in logs
    ]
    return render_template(
        "logs/index.html",
        page_title="Audit logs",
        active_nav="Logs",
        log_events=log_events,
    )


@app.get("/app/logs/<event_id>")
def app_log_detail(event_id: str) -> str:
    # show one log
    log = db.session.get(Log, int(event_id)) if event_id.isdigit() else None
    if log is None:
        abort(404)
    event = {
        "id": log.log_id,
        "date": log.logged_at.strftime("%d %b %Y, %H:%M"),
        "actor": f"User #{log.user_id}" if log.user_id else "System",
        "action": log.action,
        "record": f"{log.entity_type} #{log.entity_id}" if log.entity_type and log.entity_id else "None",
    }
    return render_template(
        "logs/detail.html",
        page_title=f"Audit event {event_id}",
        active_nav="Logs",
        event=event,
    )


if __name__ == "__main__":
    app.run(debug=False)  # debug off when local
