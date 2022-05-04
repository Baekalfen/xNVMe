import pytest

import xnvme

DEVICE_PATH = b"/dev/disk4"
BACKEND = b"macos"


@pytest.fixture
def opts():
    return xnvme.xnvme_opts(be=BACKEND)


@pytest.fixture
def dev(opts):
    device_path = DEVICE_PATH
    device = xnvme.xnvme_dev_open(device_path, opts)
    yield device
    device = xnvme.xnvme_dev_close(device)
