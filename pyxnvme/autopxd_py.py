import re


def get_definitions(pxd_f):
    data = pxd_f.read()

    member_regex = r"(.+?\n)+\n)"
    for struct in re.finditer(
        r'(cdef struct ([_a-zA-Z0-9]+)(?: "([_a-zA-Z0-9]+)")?:\n' + member_regex, data
    ):
        _, __struct_name, struct_name, _ = struct.groups()
        struct = struct.groups()[0]
        # print("struct", struct_name)
        members = []
        for member in re.finditer(
            r"(\s+([_a-zA-Z0-9]+\*?) ([_a-zA-Z0-9\[\]]+)( \".*\")?\n)", struct
        ):
            _, _type, member_name, _ = member.groups()
            # print("struct member", _type, member_name)
            members.append((_type, member_name))
        yield ("struct", struct_name, __struct_name, members)

    for union in re.finditer(
        r'(cdef union ([_a-zA-Z0-9]+)(?: "([_a-zA-Z0-9]+)")?\n' + member_regex, data
    ):
        _, __union_name, union_name, _ = union.groups()
        union = union.groups()[0]
        members = []
        for member in re.finditer(
            r"(\s+([_a-zA-Z0-9]+\*?) ([_a-zA-Z0-9\[\]]+)( \".*\")?\n)", union
        ):
            _, _type, member_name, _ = member.groups()
            members.append((_type, member_name))
        yield ("union", union_name, __union_name, members)

    for func in re.finditer(
        r'([_a-zA-Z0-9\*]+) ([_a-zA-Z0-9]+)(?: "([_a-zA-Z0-9]+)")?(\(.+\))', data
    ):
        _type, __func_name, func_name, arg_body = func.groups()

        args = []
        for arg in re.finditer(
            r"([_a-zA-Z0-9\*]+) ([_a-zA-Z0-9]+)(?:, )?", arg_body.strip("()")
        ):
            arg_type, arg_name = arg.groups()
            args.append((arg_type, arg_name))

        yield ("func", _type, func_name, __func_name, args)

    # We don't generate anything, but we can eliminate redeclarations
    for enum in re.finditer(
        r'(cpdef enum ([_a-zA-Z0-9]+)(?: "([_a-zA-Z0-9]+)")?):\n', data
    ):
        _, __enum_name, enum_name = enum.groups()
        members = []
        yield ("enum", enum_name, __enum_name, members)
    # We don't generate anything, but we can eliminate redeclarations
    for typedef in re.finditer(
        r'(ctypedef ([_a-zA-Z0-9\*]+) \(([_a-zA-Z0-9\*]+)\)(?: "([_a-zA-Z0-9]+)")?.*)\n',
        data,
    ):
        _, _ret_type, typedef_name, __typedef_name = typedef.groups()
        yield ("typedef", typedef_name.replace("*", ""), __typedef_name or "", None)


def gen_code(
    pyx_f, definitions, preamble=True, ignore_definitions=set(), lib_prefix=""
):
    if preamble:
        pyx_f.write(
            """
import cython
from cython.operator cimport dereference
from libc.string cimport memcpy
from libc.stdlib cimport calloc, free
from libc.stdint cimport uintptr_t
from cpython cimport memoryview

from libc.stdint cimport uint16_t, uint32_t, int8_t, uint64_t, int64_t, uint8_t
cimport libxnvme

cdef class xnvme_base:
    # cdef void *pointer
    cdef bint auto_free
    cdef dict ref_counting

    def __init__(self, __void_p=None, **kwargs):
        self.auto_free = False
        self.ref_counting = {}

        if __void_p:
            self._self_cast_void_p(__void_p)
        elif kwargs:
            self._self_alloc()
            self.auto_free = True
            for k,v in kwargs.items():
                self.__setattr__(k,v)

    cdef _safe_str(self, char* string):
        if <void *> string == NULL:
            return None
        return string

    def to_dict(self):
        return {x: self.__getattr__(x) for x in self.fields}

    def __del__(self):
        if self.pointer and self.auto_free:
            self._self_dealloc()

    # def void_pointer(self):
    #     return <uintptr_t> self.pointer

cdef class xnvme_void_p(xnvme_base):
    cdef void *pointer

    def __init__(self, pointer=None):
        if pointer:
            self._set_void_pointer(pointer)

    def _set_void_pointer(self, uintptr_t void_p):
        self.pointer = <void *> void_p

    def __getattr__(self, attr_name):
        if attr_name == 'void_pointer':
            return <uintptr_t> self.pointer
        if attr_name == 'pointer':
            return <uintptr_t> self.pointer
        return super().__getattr__(attr_name)

class XNVMeException(Exception):
    pass

class XNVMeNullPointerException(XNVMeException):
    pass

class StructGetterSetter:
    def __init__(self, obj, prefix):
        self.obj = obj
        self.prefix = prefix

    def __getattr__(self, name):
        if hasattr(self.obj, self.prefix+name):
            return getattr(self.obj, self.prefix+name)
        else:
            return StructGetterSetter(self.obj, self.prefix+name+'__')

    def __setattr__(self, name, value):
        if name in ['obj', 'prefix']:
            super().__setattr__(name, value)
        else:
            return setattr(self.obj, self.prefix+name, value)

# NOTE: Manually added, as it's an opaque struct that isn't picked up be the regular regex
cdef class xnvme_dev(xnvme_base):
    cdef libxnvme.xnvme_dev *pointer

    def __init__(self, __void_p=None):
        if __void_p:
            self._self_cast_void_p(__void_p)

    def _self_cast_void_p(self, void_p):
        self.pointer = <libxnvme.xnvme_dev *> void_p.pointer


# NOTE: Manually added, as it's an opaque struct that isn't picked up be the regular regex
cdef class xnvme_queue(xnvme_base):
    cdef libxnvme.xnvme_queue *pointer

    def __init__(self, __void_p=None):
        if __void_p:
            self._self_cast_void_p(__void_p)

    def _self_cast_void_p(self, void_p):
        self.pointer = <libxnvme.xnvme_queue *> void_p.pointer

# NOTE: This is the only function returning a struct directly instead of a pointer. Handled manually.
def xnvme_cmd_ctx_from_dev(xnvme_dev dev):
    cdef libxnvme.xnvme_cmd_ctx ctx = libxnvme.xnvme_cmd_ctx_from_dev(dev.pointer)
    cdef libxnvme.xnvme_cmd_ctx* ctx_p = <libxnvme.xnvme_cmd_ctx *> calloc(1, sizeof(libxnvme.xnvme_cmd_ctx))
    memcpy(<void*> ctx_p, <void*> &ctx, sizeof(libxnvme.xnvme_cmd_ctx))
    cdef xnvme_cmd_ctx ret = xnvme_cmd_ctx()
    ret.pointer = ctx_p
    return ret

# NOTE: Callback functions require some hacking, that is not worth automating
# Handler for typedef: ctypedef int (*libxnvme.xnvme_enumerate_cb "xnvme_enumerate_cb")(libxnvme.xnvme_dev* dev, void* cb_args)
cdef int xnvme_enumerate_python_callback_handler(libxnvme.xnvme_dev* dev, void* cb_args):
    (py_func, py_cb_args) = <object> cb_args
    cdef xnvme_dev py_dev = xnvme_dev()
    py_dev.pointer = dev
    return py_func(py_dev, py_cb_args)

def xnvme_enumerate(sys_uri, xnvme_opts opts, object cb_func, object cb_args):
    # Given we force the context to be a Python object, we are free to wrap it in a Python-tuple and tag our python
    # callback-function along.
    cb_args_tuple = (cb_func, cb_args)
    cdef void* cb_args_context = <void*>cb_args_tuple

    # sys_uri has a special meaning on NULL, so we translate None->NULL and otherwise pass a string along
    cdef char* _sys_uri
    if sys_uri is None:
        _sys_uri = NULL
    else:
        _sys_uri = <char*> sys_uri

    return libxnvme.xnvme_enumerate(_sys_uri, opts.pointer, xnvme_enumerate_python_callback_handler, cb_args_context)


# NOTE: Callback functions require some hacking, that is not worth automating
# Handler for typedef: ctypedef void (*libxnvme.xnvme_queue_cb "xnvme_queue_cb")(libxnvme.xnvme_cmd_ctx* ctx, void* opaque)
cdef void xnvme_queue_cb_python_callback_handler(libxnvme.xnvme_cmd_ctx* dev, void* cb_args):
    (py_func, py_cb_args) = <object> cb_args
    cdef xnvme_cmd_ctx py_ctx = xnvme_cmd_ctx()
    py_ctx.pointer = dev
    py_func(py_ctx, py_cb_args)

def xnvme_cmd_ctx_set_cb(xnvme_cmd_ctx ctx, object cb, object cb_arg):
    # Given we force the context to be a Python object, we are free to wrap it in a Python-tuple and tag our python
    # callback-function along.
    cb_args_tuple = (cb, cb_arg)
    cdef void* cb_args_context = <void*>cb_args_tuple

    libxnvme.xnvme_cmd_ctx_set_cb(ctx.pointer, xnvme_queue_cb_python_callback_handler, cb_args_context)

def xnvme_queue_set_cb(xnvme_queue queue, object cb, object cb_arg):
    # Given we force the context to be a Python object, we are free to wrap it in a Python-tuple and tag our python
    # callback-function along.
    cb_args_tuple = (cb, cb_arg)
    cdef void* cb_args_context = <void*>cb_args_tuple

    cdef int ret
    ret = libxnvme.xnvme_queue_set_cb(queue.pointer, xnvme_queue_cb_python_callback_handler, cb_args_context)
    return ret

"""
        )

    for _type, *args in definitions:
        if args[-2] in ignore_definitions:
            continue

        if _type == "struct" or _type == "union":
            _, block_name, members = args

            ignore_list = [
                "xnvme_spec_vs_register",  # Requires investigation of unions (_self_cast_void_p failing)
                "xnvmec",
            ]
            if block_name in ignore_list:
                continue

            filtered_members = [
                (t, n)
                for t, n in members
                # if "[" not in n and # TODO: Arrays are not supported yet (PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags))
                if (t.startswith("xnvme_") and t.endswith("*"))
                or (  # TODO: We can't get/set these structs yet (wrap/unwrap from xnvme python class)
                    "[" in t
                    and t != "xnvme_queue_cb"
                    and t  # TODO: Cannot assign to a callback function pointer atm.
                    != "void*"
                    and t  # TODO: Cannot assign to void pointer atm. (wrap/unwrap from xnvme_void_p python class)
                    != "xnvme_geo_type"
                    and t != "xnvme_spec_vs_register"  # TODO: Support enum types
                    and "xnvme_be_attr" not in t  # TODO: Support union types
                )  # TODO: xnvme_be_attr_list has unsupported empty array length
            ]
            fields = ", ".join(f'"{n}"' for t, n in filtered_members)

            def struct_to_class_name(t):
                return t.replace("*", "")

            setter_template = """
        if attr_name == '{member_name}':
            self.pointer.{member_name} = value
            return"""

            setter_template_struct_pointer = """
        if attr_name == '{member_name}':
            assert isinstance(value, {member_type})
            self.pointer.{member_name} = <{lib_prefix}.{__member_type}> value.void_pointer
            return"""

            setters = "\n".join(
                setter_template_struct_pointer.format(
                    lib_prefix=lib_prefix,
                    member_name=n,
                    member_type=struct_to_class_name(t),
                    __member_type=t,
                )
                if t.startswith("xnvme_") and t.endswith("*")
                else setter_template.format(member_name=n)
                for t, n in filtered_members
            )

            getter_template = """
        if attr_name == '{member_name}':
            return self.pointer.{member_name}"""

            getter_template_safe_str = """
        if attr_name == '{member_name}':
            return self._safe_str(self.pointer.{member_name})"""

            getter_template_struct_pointer = """
        if attr_name == '{member_name}':
            return {member_type}(__void_p=xnvme_void_p(<uintptr_t>self.pointer.{member_name}))"""

            getter_template_array_numpy = """
        if attr_name == '{member_name}':
            return np.ctypeslib.as_array(
                ctypes.cast(<uintptr_t>self.pointer.{member_name},
                ctypes.POINTER(ctypes.c_uint8)),shape=({member_length},))"""

            getter_template_array_xnvme = """
        if attr_name == '{member_name}':
            return StructIndexer(self, '{member_name}__', {member_length})
            return {member_type}(__void_p=xnvme_void_p(<uintptr_t>self.pointer.{member_name}))"""

            def pick_getter(t, n):
                if t == "char*":
                    return getter_template_safe_str.format(member_name=n)
                elif t.startswith("xnvme_") and t.endswith("*"):
                    return getter_template_struct_pointer.format(
                        member_name=n, member_type=struct_to_class_name(t)
                    )
                else:
                    return getter_template.format(member_name=n)

            getters = "\n".join(pick_getter(t, n) for t, n in filtered_members)

            struct_getter_template = """
        if attr_name == '{member_name}':
            return StructGetterSetter(self, '{member_name}__')"""

            struct_getters = "\n".join(
                struct_getter_template.format(member_name=n)
                for n in {
                    "__".join(n.split("__")[:-1])
                    for _, n in filtered_members
                    if "__" in n
                }
            )

            block_template = f"""
cdef class {block_name}(xnvme_base):
    cdef {lib_prefix}.{block_name} *pointer
    fields = [{fields}]

    def _self_cast_void_p(self, void_p):
        self.pointer = <{lib_prefix}.{block_name} *> void_p.pointer

    def _self_alloc(self):
        self.pointer = <{lib_prefix}.{block_name} *> calloc(1, sizeof({lib_prefix}.{block_name}))

    def _self_dealloc(self):
        free(self.pointer)

    def __setattr__(self, attr_name, value):
        if <void *> self.pointer == NULL:
            raise AttributeError('Internal pointer is not initialized. Use _self_alloc() or supply some attribute to the constructor when instantiating this object.')

        if not isinstance(value, (int, float)):
            self.ref_counting[attr_name] = value
{setters}
        raise AttributeError(f'{{self}} has no attribute {{attr_name}}')

    def __getattr__(self, attr_name):
        if <void *> self.pointer == NULL:
            raise AttributeError('Internal pointer is not initialized. Use _self_alloc() or supply some attribute to the constructor when instantiating this object.')
        if attr_name == 'sizeof':
            return sizeof({lib_prefix}.{block_name})
        if attr_name == 'void_pointer':
            return <uintptr_t> self.pointer
{getters}
{struct_getters}
        raise AttributeError(f'{{self}} has no attribute {{attr_name}}')
"""
            pyx_f.write(block_template)
        elif _type == "func":
            ret_type, _, func_name, func_args = args

            ignore_list = [
                "xnvme_be_attr_list_bundled",  # Requires investigation of pointer-pointer (xnvme_be_attr_list**)
                "xnvme_queue_init",  # Requires investigation of pointer-pointer (xnvme_queue **)
                "xnvme_buf_phys_alloc",  # Requires investigation of phys pointer (uint64_t* phys)
                "xnvme_buf_phys_realloc",  # Requires investigation of phys pointer (uint64_t* phys)
                "xnvme_buf_phys_free",  # Requires investigation of phys pointer (uint64_t* phys)
                "xnvme_buf_vtophys",  # Requires investigation of phys pointer (uint64_t* phys)
                "xnvme_cmd_ctx_from_dev",  # Manually handled
                "xnvme_enumerate",  # Manually handled
                "xnvme_cmd_ctx_set_cb",  # Manually handled
                "xnvme_queue_set_cb",  # Manually handled
                "xnvme_lba_fpr",  # uint64_t* supported yet
                "xnvme_lba_pr",  # uint64_t* supported yet
                "xnvme_lba_fprn",  # uint64_t* supported yet
                "xnvme_lba_prn",  # uint64_t* supported yet
                "xnvme_enumeration_alloc",  # Cannot assign type 'xnvme_enumeration *' to 'xnvme_enumeration **'
                "xnvme_nvm_scopy",
                "xnvmec_get_opt_attr",
                "xnvmec",
                "xnvmec_sub",
                "xnvmec_subfunc",
                "xnvmec_timer_start",
                "xnvmec_timer_stop",
                "xnvmec_timer_bw_pr",
                "xnvmec_cli_to_opts",
                "_xnvmec_cmd_from_file",
                "xnvmec_cmd_from_file",
            ]
            if func_name in ignore_list:
                continue

            _py_func_args = []
            for t, n in func_args:
                if t == "void*":
                    statement = f"xnvme_void_p {n}"
                elif t.startswith("xnvme_") or t.startswith("xnvmec_"):
                    statement = f"{t.replace('*','').replace('__','')} {n}"
                else:
                    statement = f"{t} {n}"
                _py_func_args.append(statement)
            py_func_args = ", ".join(_py_func_args)
            c_func_args = ", ".join(
                n + (".pointer" if (t[-1] == "*" and t != "char*") else "")
                for t, n in func_args
            )
            if ret_type == "void":
                func_template = f"""
def {func_name}({py_func_args}):
    {lib_prefix}.{func_name}({c_func_args})
"""
            else:
                if ret_type == "void*":
                    ret_type_def = f"xnvme_void_p"
                    assign_def = "ret.pointer"
                    verification = f'\n    if <void*> ret.pointer == NULL: raise XNVMeNullPointerException("{func_name} returned a null-pointer")'
                    init_def = f" = xnvme_void_p()"
                elif ret_type.startswith("xnvme_") or ret_type.startswith("xnvmec_"):
                    ret_type_def = f"{ret_type.replace('*','').replace('__','')}"
                    assign_def = "ret.pointer"
                    verification = f'\n    if <void*> ret.pointer == NULL: raise XNVMeNullPointerException("{func_name} returned a null-pointer")'
                    init_def = f" = {ret_type_def}()"
                else:
                    ret_type_def = ret_type
                    assign_def = "ret"
                    verification = ""
                    init_def = ""
                func_template = f"""
def {func_name}({py_func_args}):
    cdef {ret_type_def} ret{init_def}
    {assign_def} = {lib_prefix}.{func_name}({c_func_args}){verification}
    return ret
"""
            pyx_f.write(func_template)
