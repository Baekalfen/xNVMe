from setuptools import Extension
from setuptools import setup
from Cython.Build import cythonize
import os
import autopxd
import autopxd_py
import platform
import subprocess


if platform.system() == "Darwin":
    os.environ['CFLAGS'] += ' -framework IOKit -framework CoreFoundation'

stdout, _ = subprocess.Popen(['git', 'rev-parse', '--show-toplevel'], stdout=subprocess.PIPE).communicate()
git_root = stdout.strip().decode()

# Gen .pxd file from .h file
c_include_path = os.path.join(git_root, 'include')
c_header_path = os.path.join(c_include_path, 'libxnvme.h')

with open('libxnvme.pxd', 'w') as f_out, open(c_header_path, 'r') as f_in:
    regex = [
        's/SLIST_ENTRY\(xnvme_sgl\)/struct{struct xnvme_sgl *sle_next;}/g',
        's/SLIST_HEAD\(, xnvme_sgl\)/struct{struct xnvme_sgl *slh_first;}/g',
        's/SLIST_ENTRY\(xnvme_cmd_ctx\)/struct{struct xnvme_cmd_ctx *sle_next;}/g',
        's/SLIST_HEAD\(, xnvme_cmd_ctx\)/struct{struct xnvme_cmd_ctx *slh_first;}/g',
        's/FILE\s?\*/void */g',
        's/struct iovec\s?\*/void */g',
        's/xnvme_be_attr item\[\]/xnvme_be_attr *item/g',
    ]
    extra_cpp_args = [f"-I{c_include_path}"]
    f_out.write(autopxd.translate(f_in.read(), c_header_path, extra_cpp_args, debug=False, regex=regex))


# Gen CPython interface from .pxd file.
definitions = list(autopxd_py.get_definitions('libxnvme.pxd'))
autopxd_py.gen_code('libxnvme.pyx', definitions)


setup(
    name='libxnvme',
    ext_modules=cythonize([
        Extension(
            "libxnvme",
            sources=['libxnvme.pyx'],
            include_dirs=[c_include_path],
            libraries=["xnvme"],
            library_dirs=[os.path.join(git_root, 'builddir/lib/')],
        )
        ],
        annotate=True,
        language_level = "3",
    ),
    zip_safe=False,
)

