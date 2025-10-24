from decimal import Decimal, ROUND_HALF_UP

def compute_splits(parsed: dict, participants: list, mode="even") -> dict:
    """
    Compute per-person splits.
    mode: "even" or "item" (per-assignment)
    """
    n = max(1, len(participants))
    names = participants if participants else [f"P{i+1}" for i in range(n)]
    
    if mode == "even":
        total = Decimal(str(parsed.get("computed_total") or 0.0))
        share = (total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        per_person = {p: float(share) for p in names}
        return per_person

    # --- item-assignment mode ---
    items = parsed.get("items", [])
    taxes = Decimal(str(sum(t.get("amount", 0) for t in parsed.get("taxes", []))))
    service = Decimal(str(parsed.get("service_charge", {}).get("amount") or 0))
    discounts = Decimal(str(sum(d.get("amount", 0) for d in parsed.get("discounts", []))))

    subtotal_by_person = {p: Decimal("0") for p in names}
    subtotal_total = Decimal("0")
    
    for it in items:
        total_price = Decimal(str(it.get("total_price", 0)))
        assigned = it.get("assigned_to")
        if not assigned:
            for p in names:
                subtotal_by_person[p] += total_price / n
        else:
            if isinstance(assigned, list):
                for p in assigned:
                    subtotal_by_person[p] += total_price / len(assigned)
            else:
                subtotal_by_person[assigned] += total_price
        subtotal_total += total_price

    per_person = subtotal_by_person.copy()
    
    def apply_amount(amount):
        for p in names:
            proportion = (subtotal_by_person[p] / subtotal_total) if subtotal_total else 1/n
            per_person[p] += Decimal(amount) * proportion

    apply_amount(taxes + service - discounts)

    # Round final totals
    final_totals = {p: float(per_person[p].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for p in names}
    return final_totals
