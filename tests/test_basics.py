import pytest
import libxnvme

def test_dev(dev):
    assert dev
    libxnvme.xnvme_dev_pr(dev, libxnvme.XNVME_PR_DEF)

def test_ident(dev):
    ident = libxnvme.xnvme_dev_get_ident(dev)
    assert ident.nsid == 1
    assert ident.to_dict()

enumerated_devices = 0
def test_enum(opts):
    def callback_func(dev, cb_args):
        global enumerated_devices
        print(libxnvme.xnvme_dev_get_ident(dev).to_dict(),cb_args)
        enumerated_devices += 1
        return libxnvme.XNVME_ENUMERATE_DEV_CLOSE

    libxnvme.xnvme_enumerate(None, opts, callback_func, 'Awesome context!')
    assert enumerated_devices > 0

class TestBufferAlloc:
    def test_buf_alloc_free(self, dev):
        count = 5
        for i in range(count):
            buf_nbytes = 1 << i
            buf = libxnvme.xnvme_buf_alloc(dev, buf_nbytes);
            assert isinstance(buf, libxnvme.xnvme_void_p)
            libxnvme.xnvme_buf_free(dev, buf);

    def test_virt_buf_alloc_free(self, dev):
        count = 5
        for i in range(count):
            buf_nbytes = 1 << i
            buf = libxnvme.xnvme_buf_virt_alloc(0x1000, buf_nbytes);
            assert isinstance(buf, libxnvme.xnvme_void_p)
            libxnvme.xnvme_buf_virt_free(buf);


class TestLBLK:
    @pytest.fixture
    def boilerplate(self, dev):
        geo = libxnvme.xnvme_dev_get_geo(dev)
        nsid = libxnvme.xnvme_dev_get_nsid(dev);

        rng_slba = 0;
        rng_elba = (1 << 28) // geo.lba_nbytes # About 256MB

        mdts_naddr = min(geo.mdts_nbytes // geo.lba_nbytes, 256);
        buf_nbytes = mdts_naddr * geo.lba_nbytes;

        # Verify range
        assert rng_elba >= rng_slba, "Invalid range: [rng_slba,rng_elba]"

        # TODO: verify that the range is sufficiently large

        wbuf = libxnvme.xnvme_buf_alloc(dev, buf_nbytes);
        rbuf = libxnvme.xnvme_buf_alloc(dev, buf_nbytes);

        yield (dev, geo, wbuf, rbuf, buf_nbytes, mdts_naddr, nsid, rng_slba, rng_elba)

        libxnvme.xnvme_buf_free(dev, wbuf);
        libxnvme.xnvme_buf_free(dev, rbuf);


    def fill_lba_range_and_write_buffer_with_character(self, wbuf, buf_nbytes, rng_slba,rng_elba, mdts_naddr,dev, geo,nsid, character):

        # libxnvme.memset(wbuf, character, buf_nbytes);

        written_bytes = 0
        for slba in range(rng_slba, rng_elba, mdts_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            nlb = min(rng_elba - slba, mdts_naddr - 1)

            written_bytes += (1 + nlb) * geo.lba_nbytes

            err = libxnvme.xnvme_nvm_write(ctx, nsid, slba, nlb, wbuf, libxnvme.NULL);
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), f"xnvme_nvm_write(): {{err: 0x{err:x}, slba: 0x{slba:016x}}}"
        return written_bytes


    def test_verify_io(self, boilerplate):
        dev, geo, wbuf, rbuf, buf_nbytes, mdts_naddr, nsid, rng_slba, rng_elba = boilerplate

        print("Writing '!' to LBA range [slba,elba]")
        self.fill_lba_range_and_write_buffer_with_character(wbuf, buf_nbytes, rng_slba, rng_elba, mdts_naddr, dev, geo, nsid, '!');

        print("Writing payload scattered within LBA range [slba,elba]");
        assert libxnvme.xnvmec_buf_fill(wbuf, buf_nbytes, "anum") == 0

        for count in range(mdts_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev) # TODO: Reuse from before?
            wbuf_ofz = count * geo.lba_nbytes
            slba = rng_slba + count * 4

            err = libxnvme.xnvme_nvm_write(ctx, nsid, slba, 0, wbuf + wbuf_ofz, libxnvme.NULL);
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), f"xnvme_nvm_write(): {{err: 0x{err:x}, slba: 0x{slba:016x}}}"
                # libxnvme.xnvme_cmd_ctx_pr(ctx, XNVME_PR_DEF);

        print("Read scattered payload within LBA range [slba,elba]");

        libxnvme.xnvmec_buf_clear(rbuf, buf_nbytes)
        for count in range(mdts_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            rbuf_ofz = count * geo.lba_nbytes
            slba = rng_slba + count * 4

            err = libxnvme.xnvme_nvm_read(ctx, nsid, slba, 0, rbuf + rbuf_ofz, libxnvme.NULL)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), "xnvme_nvm_read(): {{err: 0x{err:x}, slba: 0x{slba:016x}}}"

        assert not libxnvme.xnvmec_buf_diff(wbuf, rbuf, buf_nbytes)
			# libxnvme.xnvmec_buf_diff_pr(wbuf, rbuf, buf_nbytes, XNVME_PR_DEF);

