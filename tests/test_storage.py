from storage import default_state, default_config

def test_defaults_exist():
    s = default_state()
    c = default_config()
    assert "month" in s
    assert "current_alloc" in c
