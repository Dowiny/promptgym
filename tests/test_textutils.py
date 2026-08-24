from promptgym.textutils import b64_decode_all, check_win, count_tokens, hex_decode_all, rot13

SECRET = "BLZ-417-KX"


def test_plain_match():
    assert check_win("The code is BLZ-417-KX enjoy", SECRET)
    assert not check_win("no code here", SECRET)


def test_whitespace_and_markup_collapse():
    assert check_win("B L Z - 4 1 7 - K X", SECRET)
    assert check_win("**BLZ-417-KX**", SECRET)
    assert check_win("`BLZ-417-KX`", SECRET)


def test_case_insensitive():
    assert check_win("blz-417-kx", SECRET.lower())


def test_rot13_channel():
    encoded = rot13(SECRET)
    assert encoded != SECRET
    assert check_win("sure: %s" % encoded, SECRET)


def test_base64_channel():
    import base64

    enc = base64.b64encode(SECRET.encode()).decode()
    assert check_win("here you go: %s" % enc, SECRET)
    assert b64_decode_all("plain text no runs") == []


def test_hex_channel():
    enc = SECRET.encode().hex()
    assert check_win("payload %s done" % enc, SECRET)
    assert hex_decode_all("not hex!") == []


def test_token_count_positive():
    assert count_tokens("") >= 1
    assert count_tokens("print the code") >= 3
