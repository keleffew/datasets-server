from .utils import URL, poll


def test_healthcheck():
    # this tests ensures the nginx reverse proxy and the api are up
    response = poll(f"{URL}/healthcheck")
    assert response.status_code == 200
    assert response.text == "ok"
