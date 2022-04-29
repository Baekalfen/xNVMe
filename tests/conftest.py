import pytest
import libxnvme

DEVICE_PATH=b'/dev/disk4'
BACKEND=b'macos'

@pytest.fixture
def opts():
    return libxnvme.xnvme_opts(be=BACKEND)


@pytest.fixture
def dev(opts):
    device_path = DEVICE_PATH
    device = libxnvme.xnvme_dev_open(device_path, opts)
    yield device
    device = libxnvme.xnvme_dev_close(device)

