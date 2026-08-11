class PrescriptionStatus:
    COMPLETED_DEFAULT = 0      # Normal billable prescription
    COMPLETED_BILLED = 1       # Billed and Dispensed
    COMPLETED_CANCELLED = 2    # Cancelled
    COMPLETED_NOT_BILLED = 3   # Exception - Not billable

    
    @classmethod
    def ACTIVE_STATUSES(cls):
        return [cls.COMPLETED_DEFAULT, cls.COMPLETED_NOT_BILLED]