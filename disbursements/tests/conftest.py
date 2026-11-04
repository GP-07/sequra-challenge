import pytest


@pytest.fixture(autouse=True)
def huey_immediate():
    """The huey tasks run in the same process, without Redis."""
    from huey.contrib.djhuey import HUEY

    previous = HUEY.immediate
    HUEY.immediate = True
    yield
    HUEY.immediate = previous
