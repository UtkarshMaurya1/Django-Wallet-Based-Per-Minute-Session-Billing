class RechargeConflict(Exception):
    """Callback contradicts the transaction's already-final state."""