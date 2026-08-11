from datetime import time, datetime, timedelta
from django.utils.timezone import make_aware
from IPD.models import DrugAdministration


FREQUENCY_TIMES = {
    'od': [time(8, 0)],
    'bd': [time(8, 0), time(20, 0)],
    'tds': [time(8, 0), time(14, 0), time(20, 0)],
    'qds': [time(6, 0), time(12, 0), time(18, 0), time(22, 0)],
}


def create_administration_schedule(prescription):

    times = FREQUENCY_TIMES.get(prescription.frequency, [])

    current = prescription.start_date

    # default 7 days if no stop date
    stop = prescription.stop_date or (current + timedelta(days=7))

    while current <= stop:

        for t in times:
            dt = make_aware(datetime.combine(current, t))

            DrugAdministration.objects.get_or_create(
                prescription=prescription,
                scheduled_time=dt
            )

        current += timedelta(days=1)
