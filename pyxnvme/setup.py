from setuptools import Extension
from setuptools import setup
from Cython.Build import cythonize
import os

os.environ['CFLAGS'] += ' -framework IOKit -framework CoreFoundation' # TODO: A better way to add this?

# TODO: Call:
# python ~/Git/Samsung/python-autopxd2/autopxd.py \
# --regex 's/SLIST_ENTRY\(xnvme_sgl\)/struct{struct xnvme_sgl *sle_next;}/g' \
# --regex 's/SLIST_HEAD\(, xnvme_sgl\)/struct{struct xnvme_sgl *slh_first;}/g' \
# --regex 's/SLIST_ENTRY\(xnvme_cmd_ctx\)/struct{struct xnvme_cmd_ctx *sle_next;}/g' \
# --regex 's/SLIST_HEAD\(, xnvme_cmd_ctx\)/struct{struct xnvme_cmd_ctx *slh_first;}/g' \
# --regex 's/FILE\s?\*/void */g' \
# --regex 's/struct iovec\s?\*/void */g' \
# --regex 's/xnvme_be_attr item\[\]/xnvme_be_attr *item/g' \
# include/libxnvme.h libxnvme.pxd
# TODO: Call:
# python autopxd_py.py

setup(
    name='libxnvme',
    ext_modules=cythonize([
        Extension(
            "libxnvme",
            sources=['libxnvme.pyx'],
            include_dirs=['include/'],
            libraries=["xnvme"],
            library_dirs=['builddir/lib/'],
        )
        ],
        annotate=True,
        language_level = "3",
    ),
    zip_safe=False,
)

