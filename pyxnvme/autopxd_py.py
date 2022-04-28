from pprint import pprint as pp
import re

def get_definitions(pxd_path):
    with open(pxd_path) as f:
        data = f.read()

        member_regex = r'(.+?\n)+\n)'
        for struct in re.finditer(r'(cdef struct ([_a-zA-Z0-9]+) "([_a-zA-Z0-9]+)":\n'+member_regex, data):
            _, __struct_name, struct_name, _ = struct.groups()
            struct = struct.groups()[0]
            # print("struct", struct_name)
            members = []
            for member in re.finditer(r'(\s+([_a-zA-Z0-9]+\*?) ([_a-zA-Z0-9\[\]]+)( \".*\")?\n)', struct):
                _, _type, member_name, _ = member.groups()
                # print("struct member", _type, member_name)
                members.append((_type, member_name))
            yield (
                "struct",
                struct_name,
                __struct_name,
                members
            )

        for union in re.finditer(r'(cdef union ([_a-zA-Z0-9]+) "([_a-zA-Z0-9]+)":\n'+member_regex, data):
            _, __union_name, union_name, _ = union.groups()
            union = union.groups()[0]
            members = []
            for member in re.finditer(r'(\s+([_a-zA-Z0-9]+\*?) ([_a-zA-Z0-9\[\]]+)( \".*\")?\n)', union):
                _, _type, member_name, _ = member.groups()
                members.append((_type, member_name))
            yield (
                "union",
                union_name,
                __union_name,
                members
            )

        for func in re.finditer(r'([_a-zA-Z0-9\*]+) ([_a-zA-Z0-9]+) "([_a-zA-Z0-9]+)"(\(.+\))', data):
            _type, __func_name, func_name, arg_body = func.groups()

            args = []
            for arg in re.finditer(r'([_a-zA-Z0-9\*]+) ([_a-zA-Z0-9]+)(?:, )?', arg_body.strip('()')):
                arg_type, arg_name = arg.groups()
                args.append((arg_type, arg_name))

            yield (
                "func",
                _type,
                func_name,
                __func_name,
                args
            )


def gen_code(pyx_path, definitions):
    with open(pyx_path, 'w') as f:
        f.write("""
import cython
from cython.operator cimport dereference
from libc.string cimport memcpy
from libc.stdlib cimport calloc, free
from libc.stdint cimport uintptr_t

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

cdef class xnvme_void_p:
    cdef void *pointer

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
    cdef __xnvme_dev *pointer

# NOTE: Manually added, as it's an opaque struct that isn't picked up be the regular regex
cdef class xnvme_queue(xnvme_base):
    cdef __xnvme_queue *pointer

# NOTE: This is the only function returning a struct directly instead of a pointer. Handled manually.
def xnvme_cmd_ctx_from_dev(xnvme_dev dev):
    cdef __xnvme_cmd_ctx ctx = __xnvme_cmd_ctx_from_dev(dev.pointer)
    cdef __xnvme_cmd_ctx* ctx_p = <__xnvme_cmd_ctx *> calloc(1, sizeof(__xnvme_cmd_ctx))
    memcpy(<void*> &ctx, <void*> ctx_p, sizeof(__xnvme_cmd_ctx))
    cdef xnvme_cmd_ctx ret = xnvme_cmd_ctx()
    ret.pointer = ctx_p
    return ret

# NOTE: Callback functions require some hacking, that is not worth automating
# Handler for typedef: ctypedef int (*__xnvme_enumerate_cb "xnvme_enumerate_cb")(__xnvme_dev* dev, void* cb_args)
cdef int xnvme_enumerate_python_callback_handler(__xnvme_dev* dev, void* cb_args):
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

    return __xnvme_enumerate(_sys_uri, opts.pointer, xnvme_enumerate_python_callback_handler, cb_args_context)


# NOTE: Callback functions require some hacking, that is not worth automating
# Handler for typedef: ctypedef void (*__xnvme_queue_cb "xnvme_queue_cb")(__xnvme_cmd_ctx* ctx, void* opaque)
cdef void xnvme_queue_cb_python_callback_handler(__xnvme_cmd_ctx* dev, void* cb_args):
    (py_func, py_cb_args) = <object> cb_args
    cdef xnvme_cmd_ctx py_ctx = xnvme_cmd_ctx()
    py_ctx.pointer = dev
    py_func(py_ctx, py_cb_args)

def xnvme_cmd_ctx_set_cb(xnvme_cmd_ctx ctx, object cb, object cb_arg):
    # Given we force the context to be a Python object, we are free to wrap it in a Python-tuple and tag our python
    # callback-function along.
    cb_args_tuple = (cb, cb_arg)
    cdef void* cb_args_context = <void*>cb_args_tuple

    __xnvme_cmd_ctx_set_cb(ctx.pointer, xnvme_queue_cb_python_callback_handler, cb_args_context)

def xnvme_queue_set_cb(xnvme_queue queue, object cb, object cb_arg):
    # Given we force the context to be a Python object, we are free to wrap it in a Python-tuple and tag our python
    # callback-function along.
    cb_args_tuple = (cb, cb_arg)
    cdef void* cb_args_context = <void*>cb_args_tuple

    cdef int ret
    ret = __xnvme_queue_set_cb(queue.pointer, xnvme_queue_cb_python_callback_handler, cb_args_context)
    return ret

#########################################################################################################
#           _    _ _______ ____          _____ ______ _   _ ______ _____         _______ ______ _____   #
#      /\  | |  | |__   __/ __ \        / ____|  ____| \ | |  ____|  __ \     /\|__   __|  ____|  __ \  #
#     /  \ | |  | |  | | | |  | |______| |  __| |__  |  \| | |__  | |__) |   /  \  | |  | |__  | |  | | #
#    / /\ \| |  | |  | | | |  | |______| | |_ |  __| | . ` |  __| |  _  /   / /\ \ | |  |  __| | |  | | #
#   / ____ \ |__| |  | | | |__| |      | |__| | |____| |\  | |____| | \ \  / ____ \| |  | |____| |__| | #
#  /_/    \_\____/   |_|  \____/        \_____|______|_| \_|______|_|  \_\/_/    \_\_|  |______|_____/  #
#########################################################################################################
""")

        for _type, *args in definitions:
            if _type == 'struct' or _type == 'union':
                block_name, __block_name, members = args

                ignore_list = [
                    'xnvme_spec_vs_register', # Requires investigation of unions (_self_cast_void_p failing)
                ]
                if block_name in ignore_list:
                    continue

                filtered_members = [
                    (t,n) for t,n in members
                    if "[" not in n and # Arrays are not supported
                       not t.startswith('__xnvme') and # and neither autogen structs
                       t != '__xnvme_queue_cb' and # TODO: Cannot assign to a callback function pointer atm.
                       t != 'void*' # TODO: Cannot assign to void pointer atm.
                ]
                fields = ', '.join(f'"{n}"' for t,n in filtered_members)

                setter_template = """
        if attr_name == '{member_name}':
            self.pointer.{member_name} = value
            return"""
                getter_template = """
        if attr_name == '{member_name}':
            return self.pointer.{member_name}"""

                getter_template_safe_str = """
        if attr_name == '{member_name}':
            return self._safe_str(self.pointer.{member_name})"""

                setters = '\n'.join(
                    setter_template.format(member_name=n) for t,n in filtered_members
                )

                getters = '\n'.join(
                    getter_template_safe_str.format(member_name=n) if t == 'char*' else getter_template.format(member_name=n)
                    for t,n in filtered_members
                )

                struct_getter_template = """
        if attr_name == '{member_name}':
            return StructGetterSetter(self, '{member_name}__')"""

                struct_getters = '\n'.join(
                    struct_getter_template.format(member_name=n)
                    for n in {'__'.join(n.split('__')[:-1]) for _,n in filtered_members if '__' in n}
                )

                block_template = f"""
cdef class {block_name}(xnvme_base):
    cdef {__block_name} *pointer
    fields = [{fields}]

    def _self_cast_void_p(self, void_p):
        self.pointer = <{__block_name} *> void_p.pointer

    def _self_alloc(self):
        self.pointer = <{__block_name} *> calloc(1, sizeof({__block_name}))

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
{getters}
{struct_getters}
        raise AttributeError(f'{{self}} has no attribute {{attr_name}}')
"""
                f.write(block_template)
            elif _type == 'func':
                ret_type, func_name, __func_name, func_args = args

                ignore_list = [
                    'xnvme_be_attr_list_bundled', # Requires investigation of pointer-pointer (__xnvme_be_attr_list**)
                    'xnvme_queue_init', # Requires investigation of pointer-pointer (__xnvme_queue **)
                    'xnvme_buf_phys_alloc', # Requires investigation of phys pointer (uint64_t* phys)
                    'xnvme_buf_phys_realloc', # Requires investigation of phys pointer (uint64_t* phys)
                    'xnvme_buf_phys_free', # Requires investigation of phys pointer (uint64_t* phys)
                    'xnvme_buf_vtophys', # Requires investigation of phys pointer (uint64_t* phys)
                    'xnvme_cmd_ctx_from_dev', # Manually handled
                    'xnvme_enumerate', # Manually handled
                    'xnvme_cmd_ctx_set_cb', # Manually handled
                    'xnvme_queue_set_cb', # Manually handled
                ]
                if func_name in ignore_list:
                    continue

                _py_func_args = []
                for t,n in func_args:
                    if t == 'void*':
                        statement = f"xnvme_void_p {n}"
                    elif t.startswith('__xnvme_'):
                        statement = f"{t.replace('*','').replace('__','')} {n}"
                    else:
                        statement = f"{t} {n}"
                    _py_func_args.append(statement)
                py_func_args = ', '.join(_py_func_args)
                c_func_args = ', '.join(n + ('.pointer' if (t[-1] == '*' and t != 'char*') else '') for t,n in func_args)
                if ret_type == 'void':
                    func_template = f"""
def {func_name}({py_func_args}):
    {__func_name}({c_func_args})
"""
                else:
                    if ret_type == 'void*':
                        ret_type_def = f"xnvme_void_p"
                        assign_def = "ret.pointer"
                        verification = f'\n    if <void*> ret.pointer == NULL: raise XNVMeNullPointerException("{func_name} returned a null-pointer")'
                        init_def = f" = xnvme_void_p()"
                    elif ret_type.startswith('__xnvme_'):
                        ret_type_def = f"{ret_type.replace('*','').replace('__','')}"
                        assign_def = "ret.pointer"
                        verification = f'\n    if <void*> ret.pointer == NULL: raise XNVMeNullPointerException("{func_name} returned a null-pointer")'
                        init_def = f" = {ret_type_def}()"
                    else:
                        ret_type_def = ret_type
                        assign_def = "ret"
                        verification = ''
                        init_def = ""
                    func_template = f"""
def {func_name}({py_func_args}):
    cdef {ret_type_def} ret{init_def}
    {assign_def} = {__func_name}({c_func_args}){verification}
    return ret
"""
                f.write(func_template)

