class MemoryViewWrapper():
    def __init__(self, ba, slice = None):
        if type(ba) == bytes:
            self.obj = memoryview(ba)
            self._slice = (0, len(ba))
            if slice is not None:
                raise ValueError("Cannot assign slice here.")
        elif type(ba) == memoryview:
            self.obj = ba
            self._slice = slice
        else:
            raise TypeError("Expected a bytes object.")

    def __len__(self):
        return self._slice[1] - self._slice[0]

    def __eq__(self, other):
        return self.obj == other

    def __ne__(self, other):
        return self.obj != other

    def __getitem__(self, index):
        # simple index access
        if type(index) == int:
            return self.obj[index]

        if index.step != None:
            raise ValueError("Step slicing is not supported.")

        # determine the positive version of the given indices
        def normalize_index(idx):
            ret = idx if idx >= 0 else len(self) + idx
            # bound from 0 to length of data
            return max(0, min(len(self), ret))

        start = 0 if index.start is None else normalize_index(index.start)
        stop = len(self) if index.stop is None else normalize_index(index.stop)
        subview = self.obj[start:stop]
        return MemoryViewWrapper(subview, (start + self._slice[0], stop + self._slice[0]))

    def _what_i_see(self):
        # for debug purpose only
        return self.obj.obj[self._slice[0]:self._slice[1]]

    def find(self, substr, start=None, end=None):
        if (start is not None and start < 0) or (end is not None and end < 0):
            raise ValueError("Bounding indices must not be a negative.")
        result = self.obj.obj.find(substr,
                          self._slice[0] + (0 if start is None else start),
                          self._slice[1] - (0 if end is None else end))
        return result if result < 0 else result - self._slice[0]

    def split(self, delim):
        ret = []
        start = 0
        while True:
            newstart = self.find(delim, start)
            if newstart < 0: break
            ret.append(self[start:newstart])
            start = newstart + len(delim)
        # latest item
        ret.append(self[start:])
        return ret
