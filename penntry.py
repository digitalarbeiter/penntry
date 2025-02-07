import inspect
import json
from functools import partial
from types import ModuleType
import requests


def walk_frames(tb):
    while tb:
        yield tb.tb_frame
        tb = tb.tb_next


def encode_frame(f):
    code = f.f_code
    source_lines, first_line_no = inspect.getsourcelines(code)
    if f.f_lineno > (len(source_lines) + first_line_no):
        # module-level: getsourceslines is broken here
        with open(code.co_filename) as file:
            source_lines = file.readlines()
            first_line_no = 0
    return {
        "locals": jsonable(f.f_locals),
        "lineno": f.f_lineno,
        "lines": source_lines,
        "first_lineno": first_line_no,
        "filename": code.co_filename,
        "name": code.co_qualname,
    }


def jsonable(thing, maxdepth=3):
    if isinstance(thing, (int, float, str, type(None), bool)):
        return thing
    if isinstance(thing, list):
        if maxdepth == 0 and thing:
            return {
                "_penntry_class": type(thing).__name__,
                "_penntry_repr": repr(thing),
            }

        return [jsonable(item, maxdepth-1) for item in thing]
    if isinstance(thing, dict):
        if maxdepth == 0 and thing:
            return {
                "_penntry_class": type(thing).__name__,
                "_penntry_repr": repr(thing),
            }
        return {
            str(k): jsonable(v, maxdepth-1) for k, v in thing.items()
            if not (k.startswith("__") and k.endswith("__"))
        }
    if isinstance(thing, tuple):
        if maxdepth == 0 and thing:
            return {
                "_penntry_class": type(thing).__name__,
                "_penntry_repr": repr(thing),
            }
        return {
            "_penntry_class": "_penntry_tuple",
            "_penntry_repr": repr(thing),
            "_penntry_values": [jsonable(item, maxdepth-1) for item in thing],
        }
    if isinstance(thing, ModuleType):
        return {
            "_penntry_class": "module",
            "_penntry_repr": thing.__name__,
        }

    if maxdepth == 0:
        return {
            "_penntry_class": type(thing).__name__,
            "_penntry_repr": repr(thing),
        }
    try:
        return {
            "_penntry_class": type(thing).__name__,
            "_penntry_repr": repr(thing),
            "_penntry_vars": jsonable(vars(thing), maxdepth-1),
        }
    except TypeError:
        return {
            "_penntry_class": type(thing).__name__,
            "_penntry_repr": repr(thing),
        }


def repr_values(thing):
    if isinstance(thing, dict):
        return {
            k: repr(v)
            for k, v in thing.items()
        }
    return [repr(item) for item in thing]


class Penntry:
    def __init__(self, server_url=None, *, contextgetter=None):
        self.server_url = server_url or "http://localhost:8000"
        self.contextgetter = contextgetter

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, tb):
        if not exc_value:
            return
        if not isinstance(exc_value, Exception):
            # for now, ignore SystemExit, KeyboardInterrupt, ...
            return
        msg = {
            "exception": [
                exc_type.__name__,
                repr(exc_value),
                repr_values(exc_value.args),
                repr_values(exc_value.__dict__),
            ],
            "frames": [
                encode_frame(f) for f in walk_frames(tb)
            ]
        }
        if self.contextgetter:
            msg["context"] = self.contextgetter()
        requests.post(f"{self.server_url}/event", json=msg)
        # print(json.dumps(msg, indent=4))


def pyramid(handler, registry):
    """
    Somewhere in your Pyramid settings:

    penntry.endpoint = http://localhost:8000

    pyramid.tweens =
        ...
        penntry.pyramid
    """
    penntry_url = registry.settings.get("penntry.endpoint", "")

    def contextgetter(request):
        ctx = {}
        for key in dir(request):
            if key.startswith("_"):
                continue
            try:
                value = getattr(request, key)
                json.dumps(value)  # non-encodable values are skipped
                ctx[key] = value
            except (TypeError, ValueError, AttributeError) as e:
                print("Can't serialize", key, e)
        return ctx

    def tween(request):
        with Penntry(penntry_url, contextgetter=partial(contextgetter, request)) as p:
            return handler(request)

    return tween
