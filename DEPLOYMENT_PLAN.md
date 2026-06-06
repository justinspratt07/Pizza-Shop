# PizzaShop Sprint 2 Deployment Plan

## HTTPS-Only Deployment Requirement

Production deployment must use HTTPS for all customer, checkout, payment, and manager/admin traffic. HTTP should only be used for local classroom testing at `http://127.0.0.1:5000`.

### Required Production Settings

Set the following environment variables before deploying behind a cloud load balancer, platform proxy, or Nginx/Apache reverse proxy:

```bash
REQUIRE_HTTPS=true
TRUST_PROXY_HEADERS=true
SECRET_KEY=<strong-random-secret>
MANAGER_PASSWORD=<strong-manager-password>
```

### HTTP to HTTPS Redirect

The Flask app now includes a `before_request` hook named `enforce_https_only`. When `REQUIRE_HTTPS=true`, non-local HTTP requests are redirected to the same URL over HTTPS using a `301` response. Localhost is excluded so classroom demos can still run without a TLS certificate.

### Reverse Proxy / Load Balancer Rules

For a production deployment, configure the edge service as follows:

1. Listen on port `443` with a valid TLS certificate.
2. Listen on port `80` only to redirect users to HTTPS.
3. Forward application traffic to Flask/Gunicorn on an internal port.
4. Preserve `X-Forwarded-Proto` and `X-Forwarded-Host` headers when `TRUST_PROXY_HEADERS=true`.

Example Nginx redirect block:

```nginx
server {
    listen 80;
    server_name pizzashop.example.com;
    return 301 https://$host$request_uri;
}
```

Example Nginx HTTPS proxy block:

```nginx
server {
    listen 443 ssl http2;
    server_name pizzashop.example.com;

    ssl_certificate /etc/letsencrypt/live/pizzashop.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pizzashop.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Sprint 2 API Flow

The Sprint 2 checkout flow is now available as separate API steps so the server remains responsible for trusted totals and payment initiation.

1. `POST /api/orders` creates a draft order from the cart or posted items.
2. `POST /api/payments/intent` creates the server-side payment intent/session for the order total.
3. `POST /api/payments/confirm` confirms the payment result and updates the order status.
4. `GET /api/orders/<order_id>` returns order and confirmation details.
5. `GET /api/order-confirmations/<order_id>` returns the confirmation-system record.
6. `GET /api/order-events` returns recent pipeline events for sprint demonstration/testing.

## Order-to-Confirmation Data Pipeline

The application now uses an explicit in-code pipeline from the place-order system to the order-confirmation system:

- `create_order()` publishes an `order_placed` event.
- `create_payment_intent()` publishes a `payment_intent_created` event.
- `confirm_payment()` publishes either `payment_succeeded` or `payment_failed`.
- Successful payment creates a separate confirmation record through `create_order_confirmation_record()`.
- Pipeline events are stored in memory and appended to `data/order_confirmation_events.jsonl` for demonstration and audit review.

This implementation keeps the project simple while showing how a production version could later replace the in-memory queue and JSON Lines file with a database table, message queue, or service bus.
