import pytest


@pytest.fixture(autouse=True)
def huey_immediate():
    """Las tasks de huey corren en el mismo proceso, sin Redis."""
    from huey.contrib.djhuey import HUEY

    previous = HUEY.immediate
    HUEY.immediate = True
    yield
    HUEY.immediate = previous
