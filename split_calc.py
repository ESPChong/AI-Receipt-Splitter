# split_calc.py
from decimal import Decimal, ROUND_HALF_UP


def _to_dec(x):
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal('0')


def compute_splits(parsed: dict, participants: list) -> dict:
    # participants: list of names or empty for equal split
    items = parsed.get('items', [])
    taxes = parsed.get('taxes', [])
    service = parsed.get('service_charge')
    discounts = parsed.get('discounts', [])

    # For demo: assume equal split unless items contain an `assigned_to` field
    n = max(1, len(participants))
    per_person = {p: Decimal('0') for p in participants} if participants else {f'P{i+1}': Decimal('0') for i in range(n)}
    names = list(per_person.keys())

    # assign items
    for it in items:
        total = _to_dec(it.get('total_price', 0))
        assigned = it.get('assigned_to')
        if not assigned:
            # split equally
            share = (total / len(names)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            for p in names:
                per_person[p] += share
        else:
            # assigned could be single or list
            if isinstance(assigned, list):
                share = (total / len(assigned)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                for p in assigned:
                    per_person[p] += share
            else:
                per_person[assigned] += total

    # add taxes and service proportionally based on subtotal
    subtotal_by_person = {p: per_person[p] for p in names}
    subtotal_total = sum(subtotal_by_person.values())
    def apply_amount(total_amount):
        if subtotal_total == 0:
            # equally
            share = (total_amount / len(names)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            for p in names:
                per_person[p] += share
        else:
            for p in names:
                prop = (subtotal_by_person[p] / subtotal_total)
                per_person[p] += (prop * total_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    for t in taxes:
        amt = _to_dec(t.get('amount', 0))
        apply_amount(amt)

    if service:
        amt = _to_dec(service.get('amount') or 0)
        apply_amount(amt)

    # apply discounts proportionally (subtract)
    for d in discounts:
        amt = _to_dec(d.get('amount', 0))
        apply_amount(-amt)

    # finalize: convert to floats
    return {p: float(per_person[p]) for p in names}