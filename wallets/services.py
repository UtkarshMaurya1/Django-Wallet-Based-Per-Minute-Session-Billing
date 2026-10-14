from django.db import transaction

from .exceptions import RechargeConflict
from .models import RechargeTransaction, Wallet

Status = RechargeTransaction.Status


def initiate_recharge(user, amount):
    return RechargeTransaction.objects.create(user=user, amount=amount)


@transaction.atomic
def process_recharge_callback(reference, new_status):
    """
    Apply a gateway callback. Returns (txn, credited).

    - Same status as already stored  -> no-op (idempotent), credited=False
    - pending -> success             -> credit wallet once, credited=True
    - pending -> failed              -> mark failed, no credit
    - any other change               -> RechargeConflict (final states are final)

    The row lock makes concurrent duplicate callbacks serialize: the second
    one waits, then sees the final status and does nothing.
    """
    txn = RechargeTransaction.objects.select_for_update().get(reference=reference)

    if txn.status == new_status:
        return txn, False

    if txn.status != Status.PENDING:
        raise RechargeConflict(
            f"Transaction {reference} is already '{txn.status}' "
            f"and cannot change to '{new_status}'."
        )

    credited = False
    if new_status == Status.SUCCESS:
        wallet = Wallet.objects.select_for_update().get(user_id=txn.user_id)
        wallet.balance += txn.amount
        wallet.save(update_fields=["balance", "updated_at"])
        credited = True

    txn.status = new_status
    txn.save(update_fields=["status", "updated_at"])
    return txn, credited