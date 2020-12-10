from json import JSONEncoder

numpy_available = True
try:
    import numpy
except (ImportError, AttributeError):
    numpy_available = False


class NumpyArrayEncoder(JSONEncoder):
    def default(self, obj):
        if numpy_available and isinstance(obj, numpy.ndarray):
            return obj.tolist()
        return JSONEncoder.default(self, obj)
