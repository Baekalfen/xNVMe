from setuptools import Extension
from setuptools import setup
from Cython.Build import cythonize
import os

os.environ['CFLAGS'] += ' -framework IOKit -framework CoreFoundation' # TODO: A better way to add this?

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

