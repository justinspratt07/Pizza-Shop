# PizzaShop Sprint 2 Submission Build

## Purpose

This folder contains the Sprint 2 source code files and Windows launcher for the PizzaShop Flask application.

## Sprint 1 and Sprint 2 Functionality

- Customer account registration
- Customer login and logout
- Customer profile display
- Pizza menu display
- Add items to a cart
- Clear cart
- Checkout form with customer name, phone, and address
- Mock payment processing
  - `tok_success` confirms payment
  - `tok_fail` simulates payment failure
- Order summary and confirmation number for successful payments
- Manager login
- Manager menu administration for adding, editing, and activating or deactivating menu items
- Manager customer order history with cancel and refund actions
- Email availability API
- Menu API
- Basic backend and route tests
- HTTPS-only production configuration with HTTP-to-HTTPS redirect support
- Server-side payment initiation endpoint for creating payment intents/sessions
- API-based checkout flow for order creation, payment intent creation, payment confirmation, and order confirmation lookup
- Order-to-confirmation data pipeline with event records in `data/order_confirmation_events.jsonl`

## Project Files

- `PizzaShopLauncher.exe` - Windows launcher. Starts the server and opens the app in a browser.
- `PizzaShopLauncher.cs` - Source code for the Windows launcher.
- `build_executable.bat` - Rebuilds `PizzaShopLauncher.exe`.
- `server.py` - Main application routes, models, validation, cart, order, payment, user, and manager logic.
- `requirements.txt` - Python dependency list.
- `templates/` - HTML templates.
- `static/css/style.css` - Page styling.
- `static/js/app.js` - Email availability and ZIP tax estimate checks.
- `data/menu.json` - Menu item data.
- `data/tax_rates.json` - Demo ZIP-based tax rate data.
- `data/users.json` - Customer account data created while running the app.
- `run_tests.py` - Sprint 2 functionality test runner.
- `DEPLOYMENT_PLAN.md` - HTTPS-only deployment plan, redirect notes, and Sprint 2 API pipeline documentation.
- `SPRINT1_CHECKLIST.md` - Sprint checklist.

## How to Run the Application

### Windows Launcher

Double-click:

```text
PizzaShopLauncher.exe
```

The launcher starts the Flask server and opens:

```text
http://127.0.0.1:5000
```

Keep the launcher window open while using the application. Press `Ctrl+C` in that window to stop the server.

### Terminal

```bash
python -m pip install -r requirements.txt
python server.py
```

Then open:

```text
http://127.0.0.1:5000
```

## How to Test the Build

```bash
python -m pip install -r requirements.txt
python run_tests.py
```

Expected final line:

```text
All Sprint 2 functional checks passed.
```

Note: `run_tests.py` creates temporary test customer accounts in `data/users.json`.

## Rebuild the Executable

After editing `PizzaShopLauncher.cs`, run:

```bat
build_executable.bat
```

## Sprint 2 API Endpoints

The server now includes the logical Sprint 2 endpoints described in the project document:

- `POST /api/orders` - creates a draft order from the current cart or from posted API items.
- `POST /api/payments/intent` - creates the server-side mock payment intent/session for the order total.
- `POST /api/payments/confirm` - confirms payment and triggers the order-confirmation pipeline.
- `GET /api/tax-estimate?zip_code=80202` - previews subtotal, ZIP-based tax, and total for the current cart.
- `GET /api/orders/<order_id>` - returns order status and confirmation details.
- `GET /api/order-confirmations/<order_id>` - returns the confirmation-system record.
- `GET /api/order-events` - returns recent place-order/payment/confirmation pipeline events for demonstration.

`POST /api/orders` accepts `zip_code` with the customer details. Tax is calculated on the server using the demo ZIP rate data in `data/tax_rates.json`, with a default rate when a ZIP is not listed. Add exact ZIPs to `rates_by_zip` or broader 3-digit fallbacks to `rates_by_prefix`.

## HTTPS Deployment Notes

For production, set `REQUIRE_HTTPS=true` so the app redirects HTTP requests to HTTPS and marks session cookies as secure. When deployed behind a reverse proxy or cloud load balancer, also set `TRUST_PROXY_HEADERS=true` so Flask respects `X-Forwarded-Proto`. Local `127.0.0.1` testing remains HTTP-friendly for the class demo. See `DEPLOYMENT_PLAN.md` for the full deployment plan.

## Demo Credentials and Test Values

- Manager password: `manager1`
- Successful payment token: `tok_success`
- Failed payment token: `tok_fail`

## Notes

This is a Flask web application. Keep the terminal running while using the local server.
