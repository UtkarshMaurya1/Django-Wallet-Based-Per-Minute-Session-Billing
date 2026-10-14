# Implementation Decisions

## 1. Django REST Framework and token authentication

Django REST Framework provides API views, serializers, authentication, permissions, and consistent HTTP error responses. DRF token authentication was selected because it satisfies the assignment's authentication requirement without introducing an external identity provider.

## 2. Custom user model and explicit roles

The project uses a custom Django user model with `USER` and `PROVIDER` roles. Providers must have a positive `per_minute_rate`; regular users must not have a provider rate. Role checks are enforced through permissions and service-level participant/state validation.

## 3. Wallet integrity at the database level

Each user has a one-to-one wallet created automatically. Wallet balance uses `DecimalField` rather than floating-point arithmetic, and a database check constraint prevents negative balances. Wallet-changing operations use database transactions and row locks where appropriate.

## 4. Mock recharge transaction and idempotency

Recharge initiation creates a `pending` transaction with a unique reference. A callback can transition it to `success` or `failed`. A successful callback credits the wallet only when the transaction is still pending. Repeating the same callback returns without another credit; conflicting changes to a final status return a conflict response.

The callback is intentionally unauthenticated to simulate a gateway webhook in this assignment. A production implementation must verify the payment provider's signature or otherwise authenticate callbacks.

## 5. Centralized session state machine

Session transition rules are centralized in the service layer. Each action declares allowed source states, target state, and actor roles. This avoids scattering lifecycle rules across API views and makes invalid transitions consistently rejectable with HTTP 400 responses.

## 6. Freeze the price at assignment

When a provider is assigned, the provider's current rate is copied into `Session.per_minute_cost`. Billing uses this snapshot rather than the provider's live rate, so a rate change does not retroactively change an existing session's price.

## 7. Minimum starting balance and one active session

Starting requires a wallet balance of at least five times the session's per-minute cost. The application checks for an existing active session, and a conditional unique database constraint provides an additional safeguard against two `in_progress` sessions for the same user.

## 8. Transactional minute-based billing

Billing calculates elapsed whole minutes, subtracts `billed_minutes`, and charges only the remaining minutes. The session row and wallet row are locked during billing, and the session stores both the number of billed minutes and the total amount billed. Repeated billing calls for the same elapsed time therefore do not charge the same minute twice.

When the remaining wallet balance cannot cover another full minute, the active session is completed by the system, with the reason recorded and the billable time persisted. User/provider end actions invoke billing before normal completion.

## 9. Synchronous billing for assignment scope

The billing endpoint triggers the billing service synchronously. This is sufficient for the assignment and avoids adding Celery, a task queue, or scheduler infrastructure that is explicitly out of scope. A production deployment would need a reliable periodic trigger and operational safeguards.

## 10. Database configuration

SQLite is the default for local development and tests. PostgreSQL can be configured using `DATABASE_URL`. Database constraints and transactional behavior are used where supported; concurrency behavior should be validated against PostgreSQL before relying on it in production.
