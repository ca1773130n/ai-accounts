from ai_accounts_core.ids import new_id


def test_new_id_has_prefix():
    assert new_id("bkd").startswith("bkd-")


def test_new_id_is_unique():
    assert new_id("bkd") != new_id("bkd")


def test_new_id_default_length():
    # prefix + "-" + 12 chars
    assert len(new_id("bkd")) == len("bkd-") + 12


def test_new_id_custom_length():
    assert len(new_id("bkd", length=6)) == len("bkd-") + 6


def test_new_id_alphabet():
    import string
    alphabet = set(string.ascii_lowercase + string.digits)
    id = new_id("xyz", length=100)
    suffix = id[len("xyz-"):]
    assert all(c in alphabet for c in suffix)
