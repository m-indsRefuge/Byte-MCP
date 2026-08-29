from byte_mcp.ox import client as client_module


def test_ox_client_allows_long_bounded_non_streaming_response_generation():
    timeout = client_module._TIMEOUT

    assert timeout.connect == 10.0
    assert timeout.read == 900.0
    assert timeout.write == 30.0
    assert timeout.pool == 10.0
