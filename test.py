# test.py
from split_calc import compute_splits

def test_equal_split():
    parsed = {'items': [{'name': 'Total', 'total_price': 90}], 'taxes': [], 'service_charge': None, 'discounts': []}
    splits = compute_splits(parsed, ['A','B','C'])
    assert round(splits['A'],2) == 30.00