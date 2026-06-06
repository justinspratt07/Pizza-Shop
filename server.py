from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from uuid import uuid4
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix
import hashlib
import json
import os
import re

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "replace-this-with-a-secure-key")
MANAGER_PASSWORD = os.environ.get("MANAGER_PASSWORD", "manager1")

# Deployment/security configuration. Local classroom demos use HTTP at 127.0.0.1,
# but production deployments should set REQUIRE_HTTPS=true so plain HTTP traffic
# is redirected to HTTPS and cookies are marked secure.
REQUIRE_HTTPS = os.environ.get("REQUIRE_HTTPS", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# When the app is behind a load balancer or reverse proxy, ProxyFix lets Flask
# respect X-Forwarded-Proto and X-Forwarded-Host. This is needed so HTTPS
# redirects and URL generation work correctly in cloud deployments.
if TRUST_PROXY_HEADERS:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=REQUIRE_HTTPS,
)

# Colab-friendly data folder. Files stored here last only for the current Colab session
# unless the project is moved to Google Drive.
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / "users.json"
MENU_FILE = DATA_DIR / "menu.json"
TAX_RATES_FILE = DATA_DIR / "tax_rates.json"
ORDER_EVENTS_FILE = DATA_DIR / "order_confirmation_events.jsonl"
EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
ZIP_CODE_REGEX = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)")
DEFAULT_SALES_TAX_RATE = Decimal("0.0700")
SALES_TAX_RATES_BY_ZIP = {}
SALES_TAX_RATES_BY_ZIP_PREFIX = {}


class OrderStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PAYMENT_FAILED = "payment_failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


@dataclass
class MenuItem:
    item_id: str
    name: str
    description: str
    price: Decimal
    active: bool = True
    photo_url: str | None = None


@dataclass
class CartItem:
    cart_item_id: str
    menu_item_id: str
    name: str
    unit_price: Decimal
    quantity: int

    def line_total(self):
        return money(self.unit_price * self.quantity)


@dataclass
class CustomerInfo:
    name: str
    phone: str
    address: str
    zip_code: str


@dataclass
class PaymentTransaction:
    payment_id: str
    order_id: str
    amount: Decimal
    status: PaymentStatus = PaymentStatus.PENDING
    provider_reference: str = ""


@dataclass
class Order:
    order_id: str
    session_id: str
    customer: CustomerInfo
    items: list
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    tax_rate: Decimal
    status: OrderStatus = OrderStatus.DRAFT
    payment_id: str = ""
    confirmation_number: str = ""
    message: str = ""
    created_at: str = ""
    updated_at: str = ""


MENU_ITEMS = {
    "p01": MenuItem(
        item_id="p01",
        name="Cheese Pizza",
        description="Classic cheese pizza with mozzarella and tomato sauce.",
        price=Decimal("10.99"),
    ),
    "p02": MenuItem(
        item_id="p02",
        name="Pepperoni Pizza",
        description="Pepperoni pizza with mozzarella and tomato sauce.",
        price=Decimal("12.99"),
    ),
    "p03": MenuItem(
        item_id="p03",
        name="Veggie Pizza",
        description="Pizza with peppers, onions, mushrooms, and olives.",
        price=Decimal("11.99"),
    ),
}

# Simple in-memory storage for the demo checkout workflow.
# User accounts are stored in users.json, but carts/orders reset when Colab restarts.
CARTS = {}
ORDERS = {}
PAYMENTS = {}

# The order confirmation pipeline models the handoff from the "place order"
# workflow into the "order confirmation" workflow. In a production application,
# these would usually be database tables, a message queue, or a service bus.
# For this course project, an in-memory list plus JSON Lines audit file keeps the
# implementation simple while still showing the integration boundary clearly.
ORDER_EVENT_PIPELINE = []
ORDER_CONFIRMATIONS = {}


def save_menu():
    rows = []
    for item in MENU_ITEMS.values():
        rows.append(
            {
                "item_id": item.item_id,
                "name": item.name,
                "description": item.description,
                "price": str(item.price),
                "active": item.active,
                "photo_url": item.photo_url,
            }
        )
    MENU_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MENU_FILE.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)


def load_menu():
    global MENU_ITEMS
    if not MENU_FILE.exists():
        save_menu()
        return
    with MENU_FILE.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    loaded = {}
    for row in rows:
        loaded[row["item_id"]] = MenuItem(
            item_id=row["item_id"],
            name=row["name"],
            description=row.get("description", ""),
            price=Decimal(str(row["price"])),
            active=bool(row.get("active", True)),
            photo_url=row.get("photo_url"),
        )
    MENU_ITEMS = loaded


load_menu()


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clean_text(value):
    return str(value or "").strip()


def normalize_zip_code(value):
    match = ZIP_CODE_REGEX.search(clean_text(value))
    return match.group(1) if match else ""


def parse_tax_rate(value):
    return Decimal(str(value)).quantize(Decimal("0.00001"))


def load_tax_rates():
    global DEFAULT_SALES_TAX_RATE
    global SALES_TAX_RATES_BY_ZIP
    global SALES_TAX_RATES_BY_ZIP_PREFIX

    if not TAX_RATES_FILE.exists():
        return

    with TAX_RATES_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    default_rate = data.get("default_rate")
    if default_rate is not None:
        DEFAULT_SALES_TAX_RATE = parse_tax_rate(default_rate)

    rates_by_zip = {}
    for zip_code, rate in data.get("rates_by_zip", {}).items():
        normalized_zip = normalize_zip_code(zip_code)
        if normalized_zip:
            rates_by_zip[normalized_zip] = parse_tax_rate(rate)

    rates_by_prefix = {}
    for prefix, rate in data.get("rates_by_prefix", {}).items():
        clean_prefix = clean_text(prefix)
        if clean_prefix.isdigit() and 1 <= len(clean_prefix) <= 4:
            rates_by_prefix[clean_prefix] = parse_tax_rate(rate)

    SALES_TAX_RATES_BY_ZIP = rates_by_zip
    SALES_TAX_RATES_BY_ZIP_PREFIX = rates_by_prefix


load_tax_rates()


def get_sales_tax_rate(zip_code):
    zip_code = normalize_zip_code(zip_code)
    if zip_code in SALES_TAX_RATES_BY_ZIP:
        return SALES_TAX_RATES_BY_ZIP[zip_code]

    for prefix_length in range(4, 0, -1):
        prefix = zip_code[:prefix_length]
        if prefix in SALES_TAX_RATES_BY_ZIP_PREFIX:
            return SALES_TAX_RATES_BY_ZIP_PREFIX[prefix]

    return DEFAULT_SALES_TAX_RATE


def format_tax_rate(rate):
    percentage = money(rate * Decimal("100"))
    return f"{percentage:.2f}%"


def get_user_zip_code(user):
    if not user:
        return ""
    return normalize_zip_code(user.get("zip_code")) or normalize_zip_code(user.get("address"))


def format_money(value):
    return f"${value:.2f}"


def mask_phone(phone):
    digits = "".join(character for character in phone if character.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***-***-{digits[-4:]}"


def current_utc_timestamp():
    """Return a consistent UTC timestamp for API and pipeline records."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_local_request():
    """Allow local classroom testing to keep using http://127.0.0.1:5000."""
    host = request.host.split(":")[0].lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def is_https_request():
    """Detect HTTPS directly or through a trusted reverse proxy header."""
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0]
    return request.is_secure or forwarded_proto.strip().lower() == "https"


def cart_item_to_api(item):
    """Convert a cart item to JSON-safe values for API responses."""
    return {
        "cart_item_id": item.cart_item_id,
        "menu_item_id": item.menu_item_id,
        "name": item.name,
        "unit_price": str(money(item.unit_price)),
        "quantity": item.quantity,
        "line_total": str(item.line_total()),
    }


def payment_to_api(payment):
    """Convert a payment transaction to a JSON-safe API response."""
    return {
        "payment_id": payment.payment_id,
        "order_id": payment.order_id,
        "amount": str(money(payment.amount)),
        "status": payment.status.value,
        "provider_reference": payment.provider_reference,
    }


def get_payment_for_order(order):
    if order.payment_id:
        return PAYMENTS.get(order.payment_id)
    return None


def order_to_api(order):
    """Convert an order to JSON-safe values for API responses."""
    payment = get_payment_for_order(order)
    return {
        "order_id": order.order_id,
        "session_id": order.session_id,
        "status": order.status.value,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "customer": {
            "name": order.customer.name,
            "phone_masked": mask_phone(order.customer.phone),
            "address": order.customer.address,
            "zip_code": order.customer.zip_code,
        },
        "items": [cart_item_to_api(item) for item in order.items],
        "subtotal": str(money(order.subtotal)),
        "tax": str(money(order.tax)),
        "tax_rate": str(order.tax_rate),
        "total": str(money(order.total)),
        "payment_id": order.payment_id,
        "payment_status": payment.status.value if payment else "",
        "confirmation_number": order.confirmation_number,
        "message": order.message,
    }


def publish_order_event(event_type, order, details=None):
    """
    Publish an order pipeline event.

    This function represents the handoff between internal subsystems. The Web UI
    or API places an order, this pipeline records the order event, and the order
    confirmation workflow can consume the resulting confirmation record.
    """
    event = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "occurred_at": current_utc_timestamp(),
        "order_id": order.order_id,
        "order_status": order.status.value,
        "payment_id": order.payment_id,
        "details": details or {},
    }

    ORDER_EVENT_PIPELINE.append(event)

    # JSON Lines is used so each event can be appended independently. This keeps
    # the demo simple and mirrors how production systems commonly write audit or
    # event-stream records.
    ORDER_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ORDER_EVENTS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")

    return event


def create_order_confirmation_record(order):
    """
    Create the confirmation-system record after a successful payment.

    The confirmation record is intentionally separate from the Order object so
    the project demonstrates a real data pipeline from order placement to order
    confirmation instead of treating confirmation as only a screen render.
    """
    payment = get_payment_for_order(order)
    confirmation = {
        "confirmation_number": order.confirmation_number,
        "order_id": order.order_id,
        "created_at": current_utc_timestamp(),
        "status": order.status.value,
        "payment_status": payment.status.value if payment else "",
        "customer_name": order.customer.name,
        "customer_phone_masked": mask_phone(order.customer.phone),
        "delivery_address": order.customer.address,
        "delivery_zip_code": order.customer.zip_code,
        "items": [cart_item_to_api(item) for item in order.items],
        "subtotal": str(money(order.subtotal)),
        "tax": str(money(order.tax)),
        "tax_rate": str(order.tax_rate),
        "total": str(money(order.total)),
        "source_pipeline": "place_order_to_order_confirmation",
    }

    ORDER_CONFIRMATIONS[order.order_id] = confirmation
    publish_order_event(
        "order_confirmation_created",
        order,
        {"confirmation_number": order.confirmation_number},
    )
    return confirmation


def get_session_id():
    """Create one cart session per browser session."""
    if "cart_session_id" not in session:
        session["cart_session_id"] = str(uuid4())
    return session["cart_session_id"]


def menu_items_for_template():
    return [item for item in MENU_ITEMS.values() if item.active]


def load_users():
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return []


def save_users(users):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as handle:
        json.dump(users, handle, indent=2)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def find_user_by_email(email: str):
    email = clean_text(email).lower()
    return next((user for user in load_users() if user["email"] == email), None)


def validate_registration_form(form):
    full_name = clean_text(form.get("full_name"))
    email = clean_text(form.get("email")).lower()
    phone = clean_text(form.get("phone"))
    address = clean_text(form.get("address"))
    zip_code = normalize_zip_code(form.get("zip_code")) or normalize_zip_code(address)
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")

    if not full_name:
        return False, "Full name is required."
    if not email or not EMAIL_REGEX.match(email):
        return False, "Please enter a valid email address."
    if find_user_by_email(email):
        return False, "An account already exists with that email."
    if not phone:
        return False, "Phone number is required."
    if not address:
        return False, "Address is required."
    if not zip_code:
        return False, "Delivery ZIP code is required."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if password != confirm_password:
        return False, "Passwords do not match."

    return True, {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "address": address,
        "zip_code": zip_code,
        "password": password,
    }


def get_current_user():
    email = session.get("user_email")
    if not email:
        return None
    return find_user_by_email(email)


def add_item_to_cart(session_id, menu_item_id, quantity):
    session_id = clean_text(session_id)
    menu_item_id = clean_text(menu_item_id)

    if not session_id:
        raise ValueError("A session ID is required.")

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a whole number.")

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if menu_item_id not in MENU_ITEMS:
        raise ValueError("Menu item was not found.")

    menu_item = MENU_ITEMS[menu_item_id]
    if not menu_item.active:
        raise ValueError("Menu item is not currently available.")

    cart_item = CartItem(
        cart_item_id=str(uuid4()),
        menu_item_id=menu_item.item_id,
        name=menu_item.name,
        unit_price=menu_item.price,
        quantity=quantity,
    )

    CARTS.setdefault(session_id, []).append(cart_item)
    return cart_item


def get_cart_totals(session_id, zip_code=""):
    cart_items = CARTS.get(session_id, [])
    subtotal = sum((item.line_total() for item in cart_items), Decimal("0.00"))
    subtotal = money(subtotal)
    tax = money(subtotal * get_sales_tax_rate(zip_code))
    total = money(subtotal + tax)
    return subtotal, tax, total


def validate_customer_info(name, phone, address, zip_code=""):
    name = clean_text(name)
    phone = clean_text(phone)
    address = clean_text(address)
    zip_code = normalize_zip_code(zip_code) or normalize_zip_code(address)

    if not name:
        raise ValueError("Customer name is required.")
    if not phone:
        raise ValueError("Customer phone number is required.")

    phone_digits = "".join(character for character in phone if character.isdigit())
    if len(phone_digits) < 10:
        raise ValueError("Customer phone number must include at least 10 digits.")
    if not address:
        raise ValueError("Customer address is required.")
    if not zip_code:
        raise ValueError("Delivery ZIP code is required.")

    return CustomerInfo(name=name, phone=phone, address=address, zip_code=zip_code)


def create_order(session_id, name, phone, address, zip_code=""):
    session_id = clean_text(session_id)
    if not session_id:
        raise ValueError("A session ID is required.")

    cart_items = CARTS.get(session_id, [])
    if not cart_items:
        raise ValueError("Cannot create an order from an empty cart.")

    customer = validate_customer_info(name, phone, address, zip_code)
    tax_rate = get_sales_tax_rate(customer.zip_code)
    subtotal, tax, total = get_cart_totals(session_id, customer.zip_code)

    timestamp = current_utc_timestamp()
    order = Order(
        order_id=str(uuid4()),
        session_id=session_id,
        customer=customer,
        items=list(cart_items),
        subtotal=subtotal,
        tax=tax,
        total=total,
        tax_rate=tax_rate,
        status=OrderStatus.DRAFT,
        message="Order created. Payment is required before confirmation.",
        created_at=timestamp,
        updated_at=timestamp,
    )
    ORDERS[order.order_id] = order
    publish_order_event(
        "order_placed",
        order,
        {
            "source": "place_order_system",
            "item_count": len(order.items),
            "delivery_zip_code": order.customer.zip_code,
            "tax_rate": str(order.tax_rate),
            "total": str(money(order.total)),
        },
    )
    return order


def create_payment_intent(order_id):
    """Create the server-side payment intent for an existing draft order.

    The browser should never calculate or submit the trusted payment amount.
    Instead, the server looks up the order total and creates the payment intent
    using that server-side amount. A real provider such as Stripe, PayPal, or
    Square would be called at this boundary.
    """
    if order_id not in ORDERS:
        raise ValueError("Order was not found.")

    order = ORDERS[order_id]

    if order.status == OrderStatus.CONFIRMED:
        raise ValueError("Payment has already been completed for this order.")
    if order.status in {OrderStatus.CANCELED, OrderStatus.REFUNDED}:
        raise ValueError("Canceled or refunded orders cannot be paid.")

    payment = PaymentTransaction(
        payment_id=str(uuid4()),
        order_id=order.order_id,
        amount=order.total,
        status=PaymentStatus.PENDING,
        provider_reference=f"mock_provider_{uuid4()}",
    )
    PAYMENTS[payment.payment_id] = payment
    order.payment_id = payment.payment_id

    publish_order_event(
        "payment_intent_created",
        order,
        {
            "payment_id": payment.payment_id,
            "amount": str(money(payment.amount)),
            "provider_reference": payment.provider_reference,
        },
    )
    return payment


def confirm_payment(order_id, payment_token):
    if order_id not in ORDERS:
        raise ValueError("Order was not found.")

    order = ORDERS[order_id]
    if order.status in {OrderStatus.CANCELED, OrderStatus.REFUNDED}:
        raise ValueError("Canceled or refunded orders cannot be paid.")
    if not order.payment_id:
        raise ValueError("Payment intent must be created before confirming payment.")

    payment = PAYMENTS[order.payment_id]
    if payment_token == "tok_success":
        payment.status = PaymentStatus.SUCCESS
        order.status = OrderStatus.CONFIRMED
        order.confirmation_number = f"PIZZA-{str(uuid4())[:8].upper()}"
        order.message = "Payment successful. Order confirmed."
        order.updated_at = current_utc_timestamp()
        CARTS[order.session_id] = []

        publish_order_event(
            "payment_succeeded",
            order,
            {"payment_id": payment.payment_id, "token_type": "mock_success"},
        )
        create_order_confirmation_record(order)
    else:
        payment.status = PaymentStatus.FAILED
        order.status = OrderStatus.PAYMENT_FAILED
        order.message = "Payment failed. Please try another payment method."
        order.updated_at = current_utc_timestamp()
        publish_order_event(
            "payment_failed",
            order,
            {"payment_id": payment.payment_id, "token_type": "mock_failure"},
        )

    return order


def cancel_order(order_id):
    if order_id not in ORDERS:
        raise ValueError("Order was not found.")

    order = ORDERS[order_id]
    if order.status == OrderStatus.CONFIRMED:
        raise ValueError("Confirmed orders must be refunded instead of canceled.")
    if order.status == OrderStatus.REFUNDED:
        raise ValueError("Refunded orders cannot be canceled.")
    if order.status == OrderStatus.CANCELED:
        raise ValueError("Order is already canceled.")

    payment = get_payment_for_order(order)
    if payment and payment.status == PaymentStatus.SUCCESS:
        raise ValueError("Paid orders must be refunded instead of canceled.")
    if payment:
        payment.status = PaymentStatus.CANCELED

    order.status = OrderStatus.CANCELED
    order.message = "Order canceled by manager."
    order.updated_at = current_utc_timestamp()
    CARTS[order.session_id] = []

    publish_order_event(
        "order_canceled",
        order,
        {"payment_id": order.payment_id, "source": "manager_order_history"},
    )
    return order


def refund_order(order_id):
    if order_id not in ORDERS:
        raise ValueError("Order was not found.")

    order = ORDERS[order_id]
    if order.status == OrderStatus.REFUNDED:
        raise ValueError("Order is already refunded.")
    if order.status == OrderStatus.CANCELED:
        raise ValueError("Canceled orders cannot be refunded.")
    if order.status != OrderStatus.CONFIRMED:
        raise ValueError("Only confirmed orders can be refunded.")

    payment = get_payment_for_order(order)
    if not payment or payment.status != PaymentStatus.SUCCESS:
        raise ValueError("A successful payment is required before refunding an order.")

    payment.status = PaymentStatus.REFUNDED
    order.status = OrderStatus.REFUNDED
    order.message = "Payment refunded by manager."
    order.updated_at = current_utc_timestamp()

    if order.order_id in ORDER_CONFIRMATIONS:
        ORDER_CONFIRMATIONS[order.order_id]["status"] = order.status.value
        ORDER_CONFIRMATIONS[order.order_id]["payment_status"] = payment.status.value
        ORDER_CONFIRMATIONS[order.order_id]["refunded_at"] = order.updated_at

    publish_order_event(
        "order_refunded",
        order,
        {
            "payment_id": payment.payment_id,
            "amount": str(money(payment.amount)),
            "source": "manager_order_history",
        },
    )
    return order


def order_for_template(order):
    """Convert an Order object into template-safe values."""
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "customer": order.customer,
        "phone_masked": mask_phone(order.customer.phone),
        "cart_items": order.items,
        "subtotal": format_money(order.subtotal),
        "tax": format_money(order.tax),
        "tax_rate": format_tax_rate(order.tax_rate),
        "total": format_money(order.total),
        "message": order.message,
        "confirmation_number": order.confirmation_number,
    }


def manager_order_for_template(order):
    payment = get_payment_for_order(order)
    return {
        "order_id": order.order_id,
        "short_id": order.order_id[:8],
        "status": order.status.value.replace("_", " ").title(),
        "status_value": order.status.value,
        "payment_status": payment.status.value.replace("_", " ").title() if payment else "None",
        "customer_name": order.customer.name,
        "customer_phone": mask_phone(order.customer.phone),
        "delivery_address": order.customer.address,
        "delivery_zip_code": order.customer.zip_code,
        "item_count": sum(item.quantity for item in order.items),
        "cart_items": order.items,
        "subtotal": format_money(order.subtotal),
        "tax": format_money(order.tax),
        "total": format_money(order.total),
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "confirmation_number": order.confirmation_number,
        "message": order.message,
        "can_cancel": order.status in {OrderStatus.DRAFT, OrderStatus.PAYMENT_FAILED},
        "can_refund": (
            order.status == OrderStatus.CONFIRMED
            and payment is not None
            and payment.status == PaymentStatus.SUCCESS
        ),
    }


def is_manager():
    return session.get("is_manager", False)


def require_manager():
    if not is_manager():
        flash("Manager login required.", "error")
        return redirect(url_for("manage_login"))
    return None


@app.context_processor
def utility_processor():
    return {
        "format_money": format_money,
        "format_tax_rate": format_tax_rate,
        "is_manager": is_manager(),
    }


@app.before_request
def enforce_https_only():
    """Redirect production HTTP traffic to HTTPS before route handling.

    The local launcher intentionally uses HTTP for classroom/demo use. In a real
    deployment, set REQUIRE_HTTPS=true and place the app behind a TLS-enabled
    reverse proxy or platform load balancer.
    """
    if not REQUIRE_HTTPS or is_local_request() or is_https_request():
        return None

    secure_url = request.url.replace("http://", "https://", 1)
    return redirect(secure_url, code=301)


@app.after_request
def add_security_headers(response):
    """Apply baseline browser security headers to every response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

    if not is_local_request() and (REQUIRE_HTTPS or is_https_request()):
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    return response


@app.route("/")
def home():
    return render_template("index.html", user=get_current_user(), menu_items=menu_items_for_template())


@app.route("/order")
def order_page():
    session_id = get_session_id()
    user = get_current_user()
    zip_code = get_user_zip_code(user)
    tax_rate = get_sales_tax_rate(zip_code)
    subtotal, tax, total = get_cart_totals(session_id, zip_code)
    return render_template(
        "order.html",
        user=user,
        menu_items=menu_items_for_template(),
        cart_items=CARTS.get(session_id, []),
        subtotal=subtotal,
        tax=tax,
        tax_rate=tax_rate,
        total=total,
        zip_code=zip_code,
    )


@app.route("/cart/add", methods=["POST"])
def cart_add():
    try:
        add_item_to_cart(
            get_session_id(),
            request.form.get("menu_item_id"),
            request.form.get("quantity", 1),
        )
        flash("Item added to cart.", "success")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("order_page"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    CARTS[get_session_id()] = []
    flash("Cart cleared.", "success")
    return redirect(url_for("order_page"))


@app.route("/checkout", methods=["POST"])
def checkout():
    user = get_current_user()
    name = request.form.get("name") or (user["full_name"] if user else "")
    phone = request.form.get("phone") or (user["phone"] if user else "")
    address = request.form.get("address") or (user["address"] if user else "")
    zip_code = request.form.get("zip_code") or get_user_zip_code(user)
    payment_token = request.form.get("payment_token", "tok_success")

    try:
        order = create_order(get_session_id(), name, phone, address, zip_code)
        create_payment_intent(order.order_id)
        order = confirm_payment(order.order_id, payment_token)
        return redirect(url_for("order_summary", order_id=order.order_id))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("order_page"))


@app.route("/orders/<order_id>")
def order_summary(order_id):
    if order_id not in ORDERS:
        flash("Order was not found.", "error")
        return redirect(url_for("order_page"))
    return render_template("summary.html", order=order_for_template(ORDERS[order_id]))


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_email"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        valid, result = validate_registration_form(request.form)
        if valid:
            new_user = {
                "full_name": result["full_name"],
                "email": result["email"],
                "phone": result["phone"],
                "address": result["address"],
                "zip_code": result["zip_code"],
                "password_hash": hash_password(result["password"]),
            }
            users = load_users()
            users.append(new_user)
            save_users(users)
            flash("Your account has been created successfully.", "success")
            return redirect(url_for("login"))
        flash(result, "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_email"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        email = clean_text(request.form.get("email")).lower()
        password = request.form.get("password", "")
        user = find_user_by_email(email)
        if user and user["password_hash"] == hash_password(password):
            session["user_email"] = user["email"]
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect(url_for("home"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/profile")
def profile():
    user = get_current_user()
    if not user:
        flash("Please log in to view your profile.", "error")
        return redirect(url_for("login"))
    return render_template("profile.html", user=user)


@app.route("/logout")
def logout():
    session.pop("user_email", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/manage", methods=["GET", "POST"])
def manage_login():
    if is_manager():
        return redirect(url_for("manage_home"))
    if request.method == "POST":
        if request.form.get("password") == MANAGER_PASSWORD:
            session["is_manager"] = True
            flash("Logged in.", "success")
            return redirect(url_for("manage_home"))
        flash("Incorrect manager password.", "error")
    return render_template("manage.html", view="login")


@app.route("/manage/home")
def manage_home():
    denied = require_manager()
    if denied:
        return denied
    return render_template("manage.html", view="logged_in")


@app.route("/manage/logout")
def manage_logout():
    session.pop("is_manager", None)
    flash("Logged out.", "success")
    return redirect(url_for("manage_login"))


@app.route("/manage/orders")
def manage_orders():
    denied = require_manager()
    if denied:
        return denied

    orders = sorted(
        ORDERS.values(),
        key=lambda order: order.created_at or "",
        reverse=True,
    )
    return render_template(
        "manage_orders.html",
        orders=[manager_order_for_template(order) for order in orders],
    )


@app.route("/manage/orders/<order_id>/cancel", methods=["POST"])
def manage_order_cancel(order_id):
    denied = require_manager()
    if denied:
        return denied

    try:
        cancel_order(order_id)
        flash("Order canceled.", "success")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("manage_orders"))


@app.route("/manage/orders/<order_id>/refund", methods=["POST"])
def manage_order_refund(order_id):
    denied = require_manager()
    if denied:
        return denied

    try:
        refund_order(order_id)
        flash("Order refunded.", "success")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("manage_orders"))


@app.route("/manage/menu")
def manage_menu():
    denied = require_manager()
    if denied:
        return denied
    return render_template("manage_menu.html", menu_items=list(MENU_ITEMS.values()))


@app.route("/manage/menu/add", methods=["POST"])
def manage_menu_add():
    denied = require_manager()
    if denied:
        return denied
    name = clean_text(request.form.get("name"))
    description = clean_text(request.form.get("description"))
    price_str = clean_text(request.form.get("price"))
    if not name or not price_str:
        flash("Name and price are required.", "error")
        return redirect(url_for("manage_menu"))
    try:
        price = money(Decimal(price_str))
    except Exception:
        flash("Price must be a valid number.", "error")
        return redirect(url_for("manage_menu"))
    item_id = f"p{str(uuid4())[:8]}"
    MENU_ITEMS[item_id] = MenuItem(
        item_id=item_id, name=name, description=description, price=price
    )
    save_menu()
    flash(f"'{name}' added to menu.", "success")
    return redirect(url_for("manage_menu"))


@app.route("/manage/menu/<item_id>/update", methods=["POST"])
def manage_menu_update(item_id):
    denied = require_manager()
    if denied:
        return denied
    if item_id not in MENU_ITEMS:
        flash("Item not found.", "error")
        return redirect(url_for("manage_menu"))
    name = clean_text(request.form.get("name"))
    description = clean_text(request.form.get("description"))
    price_str = clean_text(request.form.get("price"))
    if not name or not price_str:
        flash("Name and price are required.", "error")
        return redirect(url_for("manage_menu"))
    try:
        price = money(Decimal(price_str))
    except Exception:
        flash("Price must be a valid number.", "error")
        return redirect(url_for("manage_menu"))
    item = MENU_ITEMS[item_id]
    item.name = name
    item.description = description
    item.price = price
    save_menu()
    flash(f"'{name}' updated.", "success")
    return redirect(url_for("manage_menu"))


@app.route("/manage/menu/<item_id>/toggle", methods=["POST"])
def manage_menu_toggle(item_id):
    denied = require_manager()
    if denied:
        return denied
    if item_id not in MENU_ITEMS:
        flash("Item not found.", "error")
        return redirect(url_for("manage_menu"))
    item = MENU_ITEMS[item_id]
    item.active = not item.active
    save_menu()
    status = "active" if item.active else "inactive"
    flash(f"'{item.name}' is now {status}.", "success")
    return redirect(url_for("manage_menu"))


@app.route("/api/check-email")
def api_check_email():
    email = clean_text(request.args.get("email")).lower()
    exists = bool(find_user_by_email(email))
    return jsonify({"exists": exists})


@app.route("/api/menu")
def api_menu():
    menu_data = []
    for item in menu_items_for_template():
        data = asdict(item)
        data["price"] = format_money(item.price)
        menu_data.append(data)
    return jsonify(menu_data)


@app.route("/api/tax-estimate")
def api_tax_estimate():
    zip_code = normalize_zip_code(request.args.get("zip_code"))
    if not zip_code:
        return jsonify({"error": "A valid 5-digit ZIP code is required."}), 400

    session_id = clean_text(request.args.get("session_id")) or get_session_id()
    tax_rate = get_sales_tax_rate(zip_code)
    subtotal, tax, total = get_cart_totals(session_id, zip_code)
    return jsonify(
        {
            "zip_code": zip_code,
            "tax_rate": str(tax_rate),
            "tax_rate_display": format_tax_rate(tax_rate),
            "subtotal": format_money(subtotal),
            "tax": format_money(tax),
            "total": format_money(total),
        }
    )


@app.route("/api/orders", methods=["POST"])
def api_create_order():
    """Create a draft order from the current cart or from posted API items.

    This endpoint represents the "place order" system. It validates customer
    information, calculates totals on the server, stores the draft order, and
    publishes an order_placed event into the confirmation pipeline.
    """
    data = request.get_json(silent=True) or request.form
    session_id = clean_text(data.get("session_id")) or get_session_id()

    try:
        # API clients may send items directly. The browser UI usually builds the
        # cart first and then calls checkout, so this keeps both workflows supported.
        posted_items = data.get("items", []) if isinstance(data, dict) else []
        for item in posted_items or []:
            add_item_to_cart(
                session_id,
                item.get("menu_item_id"),
                item.get("quantity", 1),
            )

        order = create_order(
            session_id,
            data.get("name"),
            data.get("phone"),
            data.get("address"),
            data.get("zip_code"),
        )
        return jsonify({"order": order_to_api(order)}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.route("/api/payments/intent", methods=["POST"])
def api_payment_intent():
    """Create a server-side payment intent/session for a draft order.

    The client submits only the order ID. The server retrieves the order total
    and returns the mock provider reference plus a demo client secret. This
    prevents the client from controlling the final payment amount.
    """
    data = request.get_json(silent=True) or request.form
    order_id = clean_text(data.get("order_id"))

    try:
        payment = create_payment_intent(order_id)
        response = payment_to_api(payment)
        response["client_secret"] = f"mock_secret_{payment.payment_id}"
        response["message"] = "Payment intent created by server."
        return jsonify({"payment_intent": response}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.route("/api/payments/confirm", methods=["POST"])
def api_confirm_payment():
    """Confirm payment and trigger the order-confirmation pipeline.

    In the demo, tok_success approves the payment and tok_fail rejects it. A
    production provider would instead return a verified webhook or confirmation
    response that this endpoint would validate before confirming the order.
    """
    data = request.get_json(silent=True) or request.form
    order_id = clean_text(data.get("order_id"))
    payment_token = clean_text(data.get("payment_token"))

    try:
        order = confirm_payment(order_id, payment_token)
        response = {"order": order_to_api(order)}
        if order.order_id in ORDER_CONFIRMATIONS:
            response["order_confirmation"] = ORDER_CONFIRMATIONS[order.order_id]
        return jsonify(response), 200
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.route("/api/orders/<order_id>")
def api_get_order(order_id):
    """Return order status and confirmation details for API clients."""
    if order_id not in ORDERS:
        return jsonify({"error": "Order was not found."}), 404

    response = {"order": order_to_api(ORDERS[order_id])}
    if order_id in ORDER_CONFIRMATIONS:
        response["order_confirmation"] = ORDER_CONFIRMATIONS[order_id]
    return jsonify(response)


@app.route("/api/order-confirmations/<order_id>")
def api_get_order_confirmation(order_id):
    """Return the confirmation-system record created by the pipeline."""
    if order_id not in ORDER_CONFIRMATIONS:
        return jsonify({"error": "Order confirmation was not found."}), 404
    return jsonify({"order_confirmation": ORDER_CONFIRMATIONS[order_id]})


@app.route("/api/order-events")
def api_order_events():
    """Return recent pipeline events for testing and sprint demonstration."""
    return jsonify({"events": ORDER_EVENT_PIPELINE[-25:]})


def run_tests():
    CARTS.clear()
    ORDERS.clear()
    PAYMENTS.clear()
    ORDER_EVENT_PIPELINE.clear()
    ORDER_CONFIRMATIONS.clear()

    try:
        validate_customer_info("", "555-123-4567", "123 Pizza Street", "80202")
        print("Test 1 Failed")
    except ValueError:
        print("Test 1 Passed: Missing customer name was rejected.")

    test_session = "test_customer_success"
    add_item_to_cart(test_session, "p01", 1)
    test_order = create_order(
        test_session,
        "Test Customer",
        "555-111-2222",
        "100 Test Lane",
        "80202",
    )
    create_payment_intent(test_order.order_id)
    test_order = confirm_payment(test_order.order_id, "tok_success")
    assert test_order.status == OrderStatus.CONFIRMED
    assert test_order.confirmation_number != ""
    print("Test 2 Passed: Successful payment confirmed the order.")

    test_order = refund_order(test_order.order_id)
    assert test_order.status == OrderStatus.REFUNDED
    assert PAYMENTS[test_order.payment_id].status == PaymentStatus.REFUNDED
    try:
        create_payment_intent(test_order.order_id)
    except ValueError:
        pass
    else:
        raise AssertionError("Refunded orders should not accept new payment intents.")
    print("Test 3 Passed: Manager refund updated the order and payment.")

    test_session = "test_customer_failure"
    add_item_to_cart(test_session, "p02", 1)
    test_order = create_order(
        test_session,
        "Test Customer",
        "555-333-4444",
        "200 Test Avenue",
        "90001",
    )
    create_payment_intent(test_order.order_id)
    test_order = confirm_payment(test_order.order_id, "tok_fail")
    assert test_order.status == OrderStatus.PAYMENT_FAILED
    print("Test 4 Passed: Failed payment was handled correctly.")

    test_order = cancel_order(test_order.order_id)
    assert test_order.status == OrderStatus.CANCELED
    assert PAYMENTS[test_order.payment_id].status == PaymentStatus.CANCELED
    try:
        confirm_payment(test_order.order_id, "tok_success")
    except ValueError:
        pass
    else:
        raise AssertionError("Canceled orders should not accept payment confirmation.")
    print("Test 5 Passed: Manager cancel updated the order and payment.")

    denver_session = "test_zip_denver"
    los_angeles_session = "test_zip_los_angeles"
    add_item_to_cart(denver_session, "p01", 2)
    add_item_to_cart(los_angeles_session, "p01", 2)
    denver_order = create_order(
        denver_session,
        "ZIP Tester",
        "555-555-1212",
        "10 Tax Street",
        "80202",
    )
    los_angeles_order = create_order(
        los_angeles_session,
        "ZIP Tester",
        "555-555-1212",
        "10 Tax Street",
        "90001",
    )
    assert denver_order.tax_rate != los_angeles_order.tax_rate
    assert denver_order.tax != los_angeles_order.tax
    print("Test 6 Passed: ZIP-specific tax rates change the order tax.")

    client = app.test_client()
    page = client.get("/manage")
    assert page.status_code == 200
    print("Test 7 Passed: Manager login page loads.")
    bad = client.post("/manage", data={"password": "wrong"}, follow_redirects=True)
    assert b"Incorrect" in bad.data
    print("Test 8 Passed: Wrong manager password rejected.")
    ok = client.post("/manage", data={"password": MANAGER_PASSWORD}, follow_redirects=True)
    with client.session_transaction() as sess:
        assert sess.get("is_manager") is True
    print("Test 9 Passed: Manager login succeeds.")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
