import pytest
import libxnvme

@pytest.fixture
def opts():
    return libxnvme.xnvme_opts(be=b'macos')


@pytest.fixture
def dev(opts):
    device_path = b'/dev/disk4'
    device = libxnvme.xnvme_dev_open(device_path, opts)
    yield device
    device = libxnvme.xnvme_dev_close(device)

