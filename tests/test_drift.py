from engine import cumulative_alloc_drift, max_alloc_drift

def test_drift_functions():
    current = {"G": 40, "C": 30, "I": 20, "S": 5, "F": 5}
    target = {"G": 35, "C": 35, "I": 20, "S": 5, "F": 5}
    assert max_alloc_drift(current, target) == 5
    assert cumulative_alloc_drift(current, target) == 5
