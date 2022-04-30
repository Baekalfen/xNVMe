import numpy as np
import ctypes
import pytest
import libxnvme

NULL = libxnvme.xnvme_void_p(0)
UINT16_MAX = 0xFFFF

def test_dev(dev):
    assert dev, libxnvme.xnvme_dev_pr(dev, libxnvme.XNVME_PR_DEF)

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
            buf = libxnvme.xnvme_buf_alloc(dev, buf_nbytes)
            assert isinstance(buf, libxnvme.xnvme_void_p)
            libxnvme.xnvme_buf_free(dev, buf)

    def test_virt_buf_alloc_free(self, dev):
        count = 5
        for i in range(count):
            buf_nbytes = 1 << i
            buf = libxnvme.xnvme_buf_virt_alloc(0x1000, buf_nbytes)
            assert isinstance(buf, libxnvme.xnvme_void_p)
            libxnvme.xnvme_buf_virt_free(buf)


class TestLBLK:
    @pytest.fixture
    def boilerplate(self, dev):
        geo = libxnvme.xnvme_dev_get_geo(dev)
        nsid = libxnvme.xnvme_dev_get_nsid(dev)

        rng_slba = 0
        rng_elba = (1 << 26) // geo.lba_nbytes # About 64MB
        # rng_elba = (1 << 28) // geo.lba_nbytes # About 256MB

        mdts_naddr = min(geo.mdts_nbytes // geo.lba_nbytes, 256)
        buf_nbytes = mdts_naddr * geo.lba_nbytes

        # Verify range
        assert rng_elba >= rng_slba, "Invalid range: [rng_slba,rng_elba]"

        # TODO: verify that the range is sufficiently large

        wbuf = libxnvme.xnvme_buf_alloc(dev, buf_nbytes)
        rbuf = libxnvme.xnvme_buf_alloc(dev, buf_nbytes)

        yield (dev, geo, wbuf, rbuf, buf_nbytes, mdts_naddr, nsid, rng_slba, rng_elba)

        libxnvme.xnvme_buf_free(dev, wbuf)
        libxnvme.xnvme_buf_free(dev, rbuf)


    def fill_lba_range_and_write_buffer_with_character(self, wbuf, buf_nbytes, rng_slba,rng_elba, mdts_naddr,dev, geo,nsid, character):

        ctypes.memset(ctypes.c_void_p(wbuf.void_pointer), ord(character), buf_nbytes)

        written_bytes = 0
        for slba in range(rng_slba, rng_elba, mdts_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            nlb = min(rng_elba - slba, mdts_naddr - 1)

            written_bytes += (1 + nlb) * geo.lba_nbytes

            err = libxnvme.xnvme_nvm_write(ctx, nsid, slba, nlb, wbuf, NULL)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), f"xnvme_nvm_write(): {{err: 0x{err:x}, slba: 0x{slba:016x}}}"
        return written_bytes


    # /**
    #  * 0) Fill wbuf with '!'
    #  * 1) Write the entire LBA range [slba, elba] using wbuf
    #  * 2) Fill wbuf with a repeating sequence of letters A to Z
    #  * 3) Scatter the content of wbuf within [slba,elba]
    #  * 4) Read, with exponential stride, within [slba,elba] using rbuf
    #  * 5) Verify that the content of rbuf is the same as wbuf
    #  */
    def test_verify_io(self, boilerplate):
        dev, geo, wbuf, rbuf, buf_nbytes, mdts_naddr, nsid, rng_slba, rng_elba = boilerplate

        print("Writing '!' to LBA range [slba,elba]")
        self.fill_lba_range_and_write_buffer_with_character(wbuf, buf_nbytes, rng_slba, rng_elba, mdts_naddr, dev, geo, nsid, '!')

        print("Writing payload scattered within LBA range [slba,elba]")
        wbuf_mem_view = np.ctypeslib.as_array(ctypes.cast(wbuf.void_pointer,ctypes.POINTER(ctypes.c_uint8)),shape=(buf_nbytes,))
        wbuf_mem_view[:] = np.arange(len(wbuf_mem_view))
        # libxnvme.xnvmec_buf_fill(wbuf, buf_nbytes, "anum")

        for count in range(mdts_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev) # TODO: Reuse from before?
            wbuf_ofz = count * geo.lba_nbytes
            slba = rng_slba + count * 4

            err = libxnvme.xnvme_nvm_write(ctx, nsid, slba, 0, libxnvme.xnvme_void_p(wbuf.void_pointer + wbuf_ofz), NULL)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), f"xnvme_nvm_write(): {{err: 0x{err:x}, slba: 0x{slba:016x}}}"
                # libxnvme.xnvme_cmd_ctx_pr(ctx, XNVME_PR_DEF)

        print("Read scattered payload within LBA range [slba,elba]")

        rbuf_mem_view = np.ctypeslib.as_array(ctypes.cast(rbuf.void_pointer,ctypes.POINTER(ctypes.c_uint8)),shape=(buf_nbytes,))
        rbuf_mem_view[:] = 0
        assert not np.all(rbuf_mem_view == wbuf_mem_view)
        # libxnvme.xnvmec_buf_clear(rbuf, buf_nbytes)
        for count in range(mdts_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            rbuf_ofz = count * geo.lba_nbytes
            slba = rng_slba + count * 4

            err = libxnvme.xnvme_nvm_read(ctx, nsid, slba, 0, libxnvme.xnvme_void_p(rbuf.void_pointer + rbuf_ofz), NULL)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), "xnvme_nvm_read(): {{err: 0x{err:x}, slba: 0x{slba:016x}}}"

        assert np.all(rbuf_mem_view == wbuf_mem_view), libxnvme.xnvmec_buf_diff_pr(wbuf, rbuf, buf_nbytes, libxnvme.XNVME_PR_DEF)
        # assert not libxnvme.xnvmec_buf_diff(wbuf, rbuf, buf_nbytes)


    # /**
    #  * 0) Fill wbuf with '!'
    #  *
    #  * 1) Write the entire LBA range [slba, elba] using wbuf
    #  *
    #  * 2) Fill wbuf with a repeating sequence of letters A to Z
    #  *
    #  * 3) Scatter the content of wbuf within [slba,elba]
    #  *
    #  * 4) Read, with exponential stride, within [slba,elba] using rbuf
    #  *
    #  * 5) Verify that the content of rbuf is the same as wbuf
    #  */
    def test_scopy(self, boilerplate):

        # struct xnvme_spec_nvm_scopy_source_range *sranges = NULL # For the copy-payload
        sranges = []

        dev, geo, wbuf, rbuf, buf_nbytes, xfer_naddr, nsid, rng_slba, rng_elba = boilerplate

        # Force void* casting to xnvme_spec_nvm_idfy_ns*
        # xnvme_spec_nvm_idfy_ns *nvm = (void *)xnvme_dev_get_ns(dev)
        _nvm = libxnvme.xnvme_dev_get_ns(dev)
        _void_p = libxnvme.xnvme_void_p(_nvm.void_pointer)
        nvm = libxnvme.xnvme_spec_nvm_idfy_ns(__void_p=_void_p)
        libxnvme.xnvme_spec_nvm_idfy_ns_pr(nvm, libxnvme.XNVME_PR_DEF)

        if nvm.msrc:
            xfer_naddr = min(min(nvm.msrc + 1, xfer_naddr), nvm.mcl)
        buf_nbytes = xfer_naddr * geo.nbytes

        # sranges = xnvme_buf_alloc(dev, xnvme_spec_nvm_scopy_source_range().sizeof)
        # memset(sranges, 0, sizeof(*sranges))

        # Copy to the end of [slba,elba]
        sdlba = rng_elba - xfer_naddr

        # NVMe-struct copy format
        copy_fmt = libxnvme.XNVME_NVM_SCOPY_FMT_ZERO

        libxnvme.xnvme_spec_nvm_idfy_ctrlr_pr(libxnvme.xnvme_spec_nvm_idfy_ctrlr(__void_p=libxnvme.xnvme_void_p(libxnvme.xnvme_dev_get_ctrlr(dev).void_pointer)),libxnvme.XNVME_PR_DEF)
        libxnvme.xnvme_spec_nvm_idfy_ns_pr(libxnvme.xnvme_spec_nvm_idfy_ns(__void_p=libxnvme.xnvme_void_p(libxnvme.xnvme_dev_get_ns(dev).void_pointer)),libxnvme.XNVME_PR_DEF)

        self.fill_lba_range_and_write_buffer_with_character(wbuf, buf_nbytes, rng_slba, rng_elba, xfer_naddr, dev, geo, nsid, '!')

        print("Writing payload scattered within LBA range [slba,elba]")
        wbuf_mem_view = np.ctypeslib.as_array(ctypes.cast(wbuf.void_pointer,ctypes.POINTER(ctypes.c_uint8)),shape=(buf_nbytes,))
        wbuf_mem_view[:] = np.arange(len(wbuf_mem_view))
        # xnvmec_buf_fill(wbuf, buf_nbytes, "anum")
        for count in range(xfer_naddr):
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            wbuf_ofz = count * geo.lba_nbytes
            slba = rng_slba + count * 4

            sranges.append((slba, 0))
            # sranges.entry[count].slba = slba
            # sranges.entry[count].nlb = 0

            err = libxnvme.xnvme_nvm_write(ctx, nsid, slba, 0, libxnvme.xnvme_void_p(wbuf.void_pointer + wbuf_ofz), NULL)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), libxnvme.xnvme_cmd_ctx_pr(ctx, libxnvme.XNVME_PR_DEF)

        ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
        nr = xfer_naddr - 1

        print("scopy sranges to sdlba: 0x{sdlba:016x}")
        print(sranges)
        # xnvme_spec_nvm_scopy_source_range_pr(sranges, nr, XNVME_PR_DEF)

        err = libxnvme.xnvme_nvm_scopy(ctx, nsid, sdlba, sranges.entry, nr, copy_fmt)
        assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), libxnvme.xnvme_cmd_ctx_pr(ctx, libxnvme.XNVME_PR_DEF)

        print("read sdlba: 0x{sdlba:016x}")
        memset(rbuf, 0, buf_nbytes)
        err = libxnvme.xnvme_nvm_read(ctx, nsid, sdlba, nr, rbuf, NULL)
        assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), libxnvme.xnvme_cmd_ctx_pr(ctx, libxnvme.XNVME_PR_DEF)

        print("Comparing wbuf and rbuf")
        assert np.all(rbuf_mem_view == wbuf_mem_view), libxnvme.xnvmec_buf_diff_pr(wbuf, rbuf, buf_nbytes, libxnvme.XNVME_PR_DEF)

        libxnvme.xnvme_buf_free(dev, sranges)


    def read_and_compare_lba_range(self, rbuf, cbuf, rng_slba,nlb, mdts_naddr,geo, dev, nsid):
        compared_bytes = 0
        print("Reading and comparing in LBA range [%ld,%ld]", rng_slba, rng_slba + nlb)

        read_lbs = 0
        r_nlb = 0
        while read_lbs < nlb:
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            r_nlb = min(mdts_naddr, nlb - read_lbs)

            err = libxnvme.xnvme_nvm_read(ctx, nsid, rng_slba + read_lbs, r_nlb - 1, rbuf, NULL)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), "xnvme_nvm_read(): {err: 0x{err:0x}, slba: 0x{rng_slba + read_lbs:016x}}"
                # xnvme_cmd_ctx_pr(ctx, XNVME_PR_DEF)

            read_bytes = r_nlb * geo.lba_nbytes

            cbuf_mem_view = np.ctypeslib.as_array(ctypes.cast(cbuf.void_pointer,ctypes.POINTER(ctypes.c_uint8)),shape=(read_bytes,))
            rbuf_mem_view = np.ctypeslib.as_array(ctypes.cast(rbuf.void_pointer,ctypes.POINTER(ctypes.c_uint8)),shape=(read_bytes,))
            assert np.all(cbuf_mem_view == rbuf_mem_view), libxnvme.xnvmec_buf_diff_pr(cbuf, rbuf, read_bytes, libxnvme.XNVME_PR_DEF)
            compared_bytes += read_bytes

            read_lbs += r_nlb
        return compared_bytes



# /**
#  * 0) Fill wbuf with '!'
#  * 1) Write the entire LBA range [slba, elba] using wbuf
#  * 2) Make sure that we wrote '!'
#  * 3) Execute the write zeroes command
#  * 4) Fill wbuf with 0
#  * 5) Read, with exponential stride, within [slba,elba] using rbuf
#  * 6) Verify that the content of rbuf is the same as wbuf
#  */
    def test_write_zeroes(self, boilerplate):
        dev, geo, wbuf, rbuf, buf_nbytes, mdts_naddr, nsid, rng_slba, rng_elba = boilerplate
        nlb = rng_elba - rng_slba

        written_bytes = self.fill_lba_range_and_write_buffer_with_character(wbuf, buf_nbytes, rng_slba, rng_elba, mdts_naddr, dev, geo, nsid, '!')

        print(f"Written bytes {written_bytes} with !")

        rbuf_mem_view = np.ctypeslib.as_array(ctypes.cast(rbuf.void_pointer,ctypes.POINTER(ctypes.c_uint8)),shape=(buf_nbytes,))
        rbuf_mem_view[:] = 0
        # xnvmec_buf_clear(rbuf, buf_nbytes)
        compared_bytes = self.read_and_compare_lba_range(rbuf, wbuf, rng_slba, nlb, mdts_naddr, geo, dev, nsid)

        print("Compared {compared_bytes} bytes to !")

        slba = rng_slba
        while slba < rng_elba:
            ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev)
            nlb = min((rng_elba - slba) * geo.lba_nbytes, UINT16_MAX)

            err = libxnvme.xnvme_nvm_write_zeroes(ctx, nsid, slba, nlb)
            assert not (err or libxnvme.xnvme_cmd_ctx_cpl_status(ctx)), libxnvme.xnvmec_perr("xnvme_nvm_write_zeroes()", err)

            slba += mdts_naddr

        print("Wrote zeroes to LBA range [{rng_slba},{rng_elba}]")

        # Set the rbuf to != 0 so we know that we read zeroes
        memset(rbuf, 'a', buf_nbytes)
        xnvmec_buf_clear(wbuf, buf_nbytes)
        compared_bytes = self.read_and_compare_lba_range(rbuf, wbuf, rng_slba, nlb, mdts_naddr, geo, dev, nsid)
        print("Compared {compared_bytes} bytes to zero")

