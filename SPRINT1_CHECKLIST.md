# Sprint 1 Assignment Compliance Checklist

## Requirement 1: Runnable build submitted with all source code files

Met.

The submission package includes a runnable Flask application with all source files:

- `server.py`
- `requirements.txt`
- `templates/`
- `static/`
- `run_tests.py`
- `README.md`

The application can be executed with:

```bash
python server.py
```

## Requirement 2: Application includes planned Sprint 1 functionality

Met.

The current Sprint 1 build includes the following planned functionality:

| Sprint 1 function | Status |
|---|---|
| Customer registration | Complete |
| Customer login/logout | Complete |
| Customer profile page | Complete |
| Pizza menu display | Complete |
| Add menu items to cart | Complete |
| Clear cart | Complete |
| Checkout/customer information form | Complete |
| Order total, tax, and subtotal calculation | Complete |
| Mock payment success/failure handling | Complete |
| Order confirmation summary | Complete |
| Manager login | Complete |
| Manager menu administration | Complete |
| Manager order history and refund/cancel actions | Complete |
| API endpoint for email availability | Complete |
| API endpoint for menu data | Complete |
| Backend and route tests | Complete |

## Verification performed

The build was checked for Python syntax errors and tested with the included backend and route tests. The tests verified:

- Customer validation
- Successful payment confirmation
- Failed payment handling
- Manager login page loading
- Incorrect manager password rejection
- Correct manager login
- Main page route rendering
- Registration and login flow
- Cart and checkout flow
- Manager menu page rendering
