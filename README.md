### Frappe Mpesa

A custom Frappe application that integrates with Safaricom\'s Daraja API. It is built to extend ERPNext enabling seamless mobile money payments from customers, and payment disbursements to suppliers and employees. Hence it implements the following APIs: Mpesa Express, C2B, B2C and Transaction Status Query.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app frappe_mpesa
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_mpesa
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
