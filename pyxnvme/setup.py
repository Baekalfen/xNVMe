import os
import platform
import subprocess
from io import StringIO

import autopxd
import autopxd_py
from Cython.Build import cythonize
from setuptools import Extension, setup

if platform.system() == "Darwin":
    os.environ["CFLAGS"] += " -framework IOKit -framework CoreFoundation"

with subprocess.Popen(
    ["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE
) as proc:
    stdout, _ = proc.communicate()
GIT_ROOT = stdout.strip().decode()

# Gen .pxd file from .h file
c_include_path = os.path.join(GIT_ROOT, "include")

regex = [
    r"s/SLIST_ENTRY\(xnvme_sgl\)/struct{struct xnvme_sgl *sle_next;}/g",
    r"s/SLIST_HEAD\(, xnvme_sgl\)/struct{struct xnvme_sgl *slh_first;}/g",
    r"s/SLIST_ENTRY\(xnvme_cmd_ctx\)/struct{struct xnvme_cmd_ctx *sle_next;}/g",
    r"s/SLIST_HEAD\(, xnvme_cmd_ctx\)/struct{struct xnvme_cmd_ctx *slh_first;}/g",
    r"s/FILE\s?\*/void */g",
    r"s/struct iovec\s?\*/void */g",
    r"s/xnvme_be_attr item\[\]/xnvme_be_attr item[1]/g",
    # r's/xnvme_be_attr item\[\]/xnvme_be_attr *item/g',
    r"s/xnvme_ident entries\[\]/xnvme_ident entries[1]/g",
    # r's/xnvme_ident entries\[\]/xnvme_ident *entries/g',
]
extra_cpp_args = [f"-I{c_include_path}"]

pxd_contents = StringIO()
pyx_contents = StringIO()
definition_names = {
    "xnvme_spec_vs_register",
}  # set()
preamble = True  # noqa

# TODO: Split into libxnvme.pxd/pyx, libxnvme_pp.pxd/pyx, libxnvme_nvm.pxd/pyx
for h_file in ["libxnvme.h", "libxnvme_nvm.h", "libxnvme_pp.h"]:  # , 'libxnvmec.h']:
    h_path = os.path.join(c_include_path, h_file)
    with open(h_path, "r") as f_in:
        pxd_contents.write(
            autopxd.translate(
                f_in.read(),
                h_path,
                extra_cpp_args,
                debug=False,
                regex=regex,
                additional_ignore_declarations=definition_names,
            )
        )

    # Gen CPython interface from .pxd file.
    pxd_contents.seek(0)
    definitions = list(autopxd_py.get_definitions(pxd_contents))

    _definition_names = {d[-2] for d in definitions}
    _definition_names |= {d[-2] + "*" for d in definitions}
    _definition_names |= {d[-2] + "**" for d in definitions}

    autopxd_py.gen_code(
        pyx_contents,
        definitions,
        preamble=preamble,
        ignore_definitions=definition_names,
        lib_prefix="libxnvme",
    )
    preamble = False

    definition_names = _definition_names | definition_names

# for f_name, contents in [('libxnvme_pp.pxd', pxd_contents), ('libxnvme_pp.pyx', pyx_contents)]:
for f_name, contents in [("libxnvme.pxd", pxd_contents), ("xnvme.pyx", pyx_contents)]:
    with open(f_name, "w") as f_out:
        contents.seek(0)
        f_out.write(contents.read())

# TODO: Fix enums
# os.system(f"sed -i '' 's/xnvme_pr/__xnvme_pr/g' xnvme.pyx")
# os.system(f"sed -i '' 's/xnvme_nvm_scopy_fmt/__xnvme_nvm_scopy_fmt/g' xnvme.pyx")

os.system("sed -i '' 's/xnvme_spec_vs_register ver//g' libxnvme.pxd")


# os.system(f"sed -i '' 's/xnvmec_get_opt_attr(xnvmec_opt/xnvmec_get_opt_attr(__xnvmec_opt/g' xnvme.pyx")
# os.system(f"sed -i '' 's/int given\[\]/int *given/g' libxnvme.pxd")

setup(
    name="xnvme",
    ext_modules=cythonize(
        [
            Extension(
                "xnvme",
                sources=["xnvme.pyx"],
                include_dirs=[c_include_path],
                libraries=["xnvme"],
                library_dirs=[os.path.join(GIT_ROOT, "builddir/lib/")],
            ),
            # Extension(
            #     "libxnvme_pp",
            #     sources=['libxnvme_pp.pyx'],
            #     include_dirs=[c_include_path],
            #     libraries=["xnvme"],
            #     library_dirs=[os.path.join(git_root, 'builddir/lib/')],
            # )
        ],
        annotate=False,
        language_level="3",
    ),
    zip_safe=False,
)
