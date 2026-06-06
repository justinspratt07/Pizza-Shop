# Sprint 2 Payment Data-Flow Diagram and Trust Boundaries

```mermaid
flowchart LR
    browser[Customer Browser / Web UI]
    provider[External Payment Provider / Hosted Checkout]
    server[PizzaShop Flask Server / Backend API]
    confirm[Order Confirmation Record]

    browser -- "order ID + mock payment token" --> provider
    provider -- "provider reference + payment status" --> server
    server -- "validated order total + payment intent" --> provider
    server -- "confirmation number + itemized totals" --> confirm
    confirm -- "summary display" --> browser

    subgraph B1[Trust boundary: client to provider]
      browser
      provider
    end

    subgraph B2[Trust boundary: provider to server]
      server
      confirm
    end
```

## Notes

- The browser does not submit the trusted payment amount.
- The server calculates subtotal, ZIP-based tax, and final total before creating the payment intent.
- PizzaShop stores payment status and provider reference only; no card numbers are stored.
- Production deployment must use HTTPS for customer, checkout, payment, and manager/admin traffic.
