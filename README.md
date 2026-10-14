# Django Wallet-Based Per-Minute Session Billing

A Django REST Framework backend for paid one-to-one consultation sessions. Users maintain a prepaid wallet, book a provider, start and end a session through a controlled state machine, and are charged for elapsed whole minutes. A session is completed automatically when the wallet cannot cover the next minute.

## Features

- Custom user model with `USER` and `PROVIDER` roles.
- Token-based authentication.
- A wallet automatically created for every user.
- Mock wallet recharge with `pending`, `success`, and `failed` transaction states.
- Idempotent recharge callbacks: a successful transaction credits the wallet only once.
- Session state machine with role and participant checks.
- Provider's per-minute rate copied to the session when assigned, so later provider-rate changes do not change the session price.
- Minimum starting balance of five times the session's per-minute cost.
- At most one `in_progress` session per user, enforced in service logic and by a database constraint.
- Transactional minute-based billing with row locks and billed-minute tracking.
- Automatic completion when the wallet cannot cover another full minute.
- Tests for wallet rules, recharge idempotency, state transitions, permissions, and billing behavior.

## Technology

- Python
- Django
- Django REST Framework
- DRF token authentication
- SQLite for local development

## Project layout

```text
consult_project/
├── manage.py
├── config/          # Settings and root URL configuration
├── accounts/        # Custom user, roles, registration, authentication
├── wallets/         # Wallet, recharge transactions, mock callback
├── consultations/   # Session model, state machine, billing, API
├── requirements.txt
├── README.md
├── STATE_DIAGRAM.md
├── IMPLEMENTATION_DECISIONS.md
└── .gitignore
```

Keep the documentation and `requirements.txt` in the same project root as `manage.py`.

## Setup

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment variables

For local development, the project defaults to SQLite. The current settings use a development-only fallback secret key and `DEBUG=1`; override these for any non-local deployment.

PowerShell example:

```powershell
$env:SECRET_KEY = "replace-with-a-long-random-secret"
$env:DEBUG = "1"
$env:ALLOWED_HOSTS = "127.0.0.1,localhost"
```

Do not commit real credentials or `.env` files.

### 4. Apply migrations and run the server

```bash
python manage.py migrate
python manage.py runserver
```

The local API is available at `http://127.0.0.1:8000/`.

## Authentication and roles

Registration returns a token. Use it in subsequent requests as:

```http
Authorization: Token YOUR_TOKEN
```

Register a regular user:

```http
POST /api/auth/register/
Content-Type: application/json

{
  "username": "alice",
  "password": "strong-password-123",
  "role": "USER"
}
```

Register a provider with a positive per-minute rate:

```http
POST /api/auth/register/
Content-Type: application/json

{
  "username": "provider1",
  "password": "strong-password-123",
  "role": "PROVIDER",
  "per_minute_rate": "50.00"
}
```

Login with the credentials to obtain a token:

```http
POST /api/auth/login/
Content-Type: application/json

{
  "username": "alice",
  "password": "strong-password-123"
}
```

Get the authenticated user's profile:

```http
GET /api/auth/me/
Authorization: Token YOUR_TOKEN
```

## API endpoints

All endpoints below are relative to the server root. Protected endpoints require token authentication unless stated otherwise.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/auth/register/` | Register a user or provider; returns a token |
| `POST` | `/api/auth/login/` | Obtain a token |
| `GET` | `/api/auth/me/` | Get the current user's profile |
| `GET` | `/api/wallet/` | View the current user's wallet balance |
| `POST` | `/api/wallet/recharge/` | Initiate a mock recharge |
| `POST` | `/api/wallet/recharge/callback/` | Process a mock payment callback; intentionally unauthenticated for this assignment |
| `GET` | `/api/sessions/` | List sessions involving the authenticated user |
| `POST` | `/api/sessions/` | Create an unassigned session (USER only) |
| `GET` | `/api/sessions/{id}/` | Retrieve a session if the requester is a participant |
| `POST` | `/api/sessions/{id}/assign/` | Assign a provider (USER; body contains `provider_id`) |
| `POST` | `/api/sessions/{id}/accept/` | Provider accepts the session |
| `POST` | `/api/sessions/{id}/start/` | User starts an accepted session if the minimum balance is available |
| `POST` | `/api/sessions/{id}/bill/` | Trigger billing for elapsed whole minutes |
| `POST` | `/api/sessions/{id}/end/` | User or assigned provider ends an active session; elapsed billable minutes are processed first |
| `POST` | `/api/sessions/{id}/cancel/` | User or assigned provider cancels a session before it starts |

### Mock recharge flow

1. The authenticated user initiates a recharge:

   ```http
   POST /api/wallet/recharge/
   Authorization: Token USER_TOKEN
   Content-Type: application/json

   {"amount": "500.00"}
   ```

2. Save the returned `reference`. The transaction starts as `pending`; the wallet is not credited yet.
3. Simulate a successful callback:

   ```http
   POST /api/wallet/recharge/callback/
   Content-Type: application/json

   {"reference": "RCH-REFERENCE-FROM-RESPONSE", "status": "success"}
   ```

4. A repeated successful callback for the same reference is a no-op and does not credit the wallet again. To simulate failure, send `"status": "failed"` while the transaction is pending.

> **Security note:** The callback endpoint is deliberately unauthenticated to simulate a gateway webhook in this assignment. It is not suitable for public production use without authenticating/verifying callbacks.

### Session flow

1. Register a `USER` and a `PROVIDER`.
2. Recharge the user's wallet and process the mock success callback.
3. The user creates a session with `POST /api/sessions/`.
4. The user assigns a provider with `POST /api/sessions/{id}/assign/` and body `{"provider_id": PROVIDER_ID}`.
5. The assigned provider accepts the session.
6. The user starts the session. The wallet must contain at least `5 × per_minute_cost`.
7. Trigger `POST /api/sessions/{id}/bill/` periodically to bill newly elapsed whole minutes.
8. The user or provider can end the session. The end operation bills elapsed whole minutes before normal completion. If the wallet cannot cover another full minute, the billing service completes the session with `ended_by = "system"` and `end_reason = "Insufficient Balance"`.

Billing is triggered synchronously through the API; no background worker or scheduler is required by this assignment.

## Billing rules

- Only complete elapsed minutes are billed.
- `billed_minutes` tracks the number of minutes already charged.
- `total_billed` tracks the total amount charged for the session.
- Each billing operation charges only newly elapsed minutes.
- Session and wallet rows are locked during billing to reduce the risk of concurrent duplicate charges.
- Wallet balance is constrained to be non-negative at the database level.
- When the remaining balance is below the per-minute rate, an active session is completed by the system.

## Run tests

Run the consultation tests:

```bash
python manage.py test consultations
```

Run the full test suite:

```bash
python manage.py test
```

The project was previously reported by the developer to pass both commands locally. Re-run them after the final documentation and cleanup changes.

## Assignment scope and limitations

This is an interview assignment implementation. It uses a mock recharge callback, synchronous billing, and no frontend, real payment gateway, chat, WebRTC, admin workflow, or production background workers. Production deployment would require stronger secret management, callback verification, rate limiting, operational monitoring, and a defined billing scheduler.
