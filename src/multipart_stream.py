from enum import Enum, auto
import re
import os
import time
from memoryviewbyteutils import MemoryViewWrapper


class _States(Enum):
    READY = auto(),
    CD_HDR = auto(),
    DATA = auto(),
    DATA_END = auto(),
    FINISHED = auto()


class MultipartStream:
    def __init__(self, scope, path, look_for):
        # const
        self._CRLF = b'\r\n'
        # initial variables
        self._boundary = None
        self._old_chunk = None
        self._cd_str = None
        self._cd_name = None
        self._cd_filename = None
        self._saved_data_chunk = None
        self._data_end_marker = None
        self._fh = None
        self._path = path
        # this is the field that we're looking after
        if not hasattr(look_for, 'decode'): raise TypeError("Expected bytes-like object for look_for.")
        self._look_for = look_for
        # initial parsing of header data
        self._parse_header_content(scope)
        # initial states
        self._state = _States.READY

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def _parse_header_content(self, scope):
        for tpl in scope['headers']:
            if tpl[0] == b'content-type':
                ct_params = MemoryViewWrapper(tpl[1]).split(b'; ')
                if ct_params[0].obj != b'multipart/form-data':
                    raise ValueError("Invalid content type.")
                for ct_param in ct_params:
                    ct_tpl = ct_param.split(b'=')
                    if len(ct_tpl) != 2: continue
                    if ct_tpl[0].obj == b'boundary':
                        self._boundary = b'--' + ct_tpl[1].obj.tobytes()
                        break
                break
        if self._boundary is None:
            raise ValueError("Header content-type not found or valid.")

    def _find_boundary_end(self, newchunk, start_from = 0, boundary_str = True, pre_crlf = 0, post_crlf = 0):
        """:return Index of the character after the last character of the first occurrence of the boundary string,
            or -1 if the boundary string is not found"""
        boundary = b''.join([self._CRLF for i in range(pre_crlf)] +
                            [self._boundary if boundary_str else b''] +
                            [self._CRLF for i in range(post_crlf)])

        if start_from == 0:
            if self._old_chunk is not None:
                # first, we perform a check to ensure that the boundary that we are after isn't chunked
                # this assumes that each chunk is larger that the boundary string
                # find last letter that matches the boundary string
                last_letter = boundary[-1]
                for i in range(min(len(newchunk), len(boundary)) - 1, -1, -1):
                    if newchunk[i] == last_letter:
                        newchunk_portion = newchunk[:i+1]
                        if boundary.endswith(newchunk_portion.obj):
                            # we join the old chunk with the new one, and ensure that it ends with the boundary string
                            if (self._old_chunk.obj.obj + bytes(newchunk_portion)).endswith(boundary):
                                # then this is the boundary!
                                return i + 1
        # let's find a regular occurrence
        idx = newchunk.find(boundary, start_from)
        return -1 if idx < 0 else idx + len(boundary)


    def _parse_cd_str(self):
        """Parse the complete content-disposition subheader stored in _cd_str"""
        ret = {'field_name':None, 'file_name':None}
        lines = self._cd_str.split(b'\r\n')
        for line in lines:
            splt = line.split(b": ")
            if len(splt) >= 2 and splt[0] == b'Content-Disposition':
                splt = splt[1].split(b"; ")
                if len(splt) >= 2 and splt[0] == b'form-data':
                    for i in range(1, len(splt)):
                        splt2 = splt[i].split(b'=')
                        if splt2[0] == b'name' and len(splt2) == 2:
                            # always assume quoted string
                            ret['field_name'] = splt2[1][1:-1].obj.tobytes()
                        elif splt2[0] == b'filename' and len(splt2) == 2:
                            # always assume quoted string
                            ret['file_name'] = splt2[1][1:-1].obj.tobytes()
            # We've already found the data we need. No point to proceed any further.
            if ret['field_name'] is not None:
                # default timestamp based file name if not specified by client
                if ret['file_name'] is None or len(ret['file_name'].strip()) == 0:
                    ret['file_name'] = f"upload-{int(time.time())}.dat".encode('UTF-8')
                break
        return ret

    def add_chunk(self, chunk):
        if self._state == _States.FINISHED:
            # no more data can't be processed. please create a new instance
            return False
        if len(chunk) == 0:
            return True

        mv_chunk = MemoryViewWrapper(chunk)
        start_idx = 0

        while True:
            if self._state == _States.READY:
                # look for the boundary, so we can determine the content-disposition header
                start_idx = self._find_boundary_end(mv_chunk, start_idx, True, 0, 1)
                if start_idx >= 0:
                    self._cd_str = b''
                    self._state = _States.CD_HDR
                else:
                    # proceed on the next chunk
                    break
            elif self._state == _States.CD_HDR:
                # here, we will parse the content-disposition (sub)header
                prev_start_idx = start_idx
                boundary_size = 4
                start_idx = self._find_boundary_end(mv_chunk, start_idx, False, 2)
                if start_idx >= 0:
                    self._cd_str += bytes(mv_chunk[prev_start_idx:max(0, start_idx - boundary_size)])
                    self._cd_str = MemoryViewWrapper(self._cd_str)
                    # ensure that we don't include a part of the boundary if the boundary is truncated
                    if start_idx < boundary_size: self._cd_str = self._cd_str[:start_idx - boundary_size]
                    hdr_parse = self._parse_cd_str()
                    # be ready to open the file for writing if we encountered the correct form field
                    self._fh = open(os.path.join(self._path, hdr_parse['file_name'].decode()), 'wb') if hdr_parse['field_name'] == self._look_for else None
                    self._state = _States.DATA
                    self._saved_data_chunk = None
                else:
                    self._cd_str += bytes(mv_chunk[prev_start_idx:])
                    # proceed to the next chunk
                    break
            elif self._state == _States.DATA:
                # a boundary is the end of data
                prev_start_idx = start_idx
                start_idx = self._find_boundary_end(mv_chunk, start_idx, True, 1)
                # begin processing and writing only if _fh is assigned
                if self._fh is not None:
                    boundary_size = len(self._boundary) + 2
                    if start_idx < 0:
                        # this means that we couldn't find an exact match for the boundary
                        # if there is a saved chunk, it is certain that the chunk contains only data, no boundary
                        if self._saved_data_chunk is not None:
                            self._fh.write(self._saved_data_chunk.obj)
                            self._saved_data_chunk = None
                        # we save this chunk first, in case the last part of the chunk contains a part of the boundary
                        self._saved_data_chunk = mv_chunk[prev_start_idx:]
                    else:
                        # write the previous chunk if exist
                        if self._saved_data_chunk is not None:
                            # ensure that we don't include the partial boundary data stored here
                            if start_idx < boundary_size:
                                self._saved_data_chunk = self._saved_data_chunk[:start_idx - boundary_size]
                            self._fh.write(self._saved_data_chunk.obj)
                            self._saved_data_chunk = None
                        # data from current (last!) chunk
                        if start_idx > boundary_size:
                            self._fh.write(mv_chunk[prev_start_idx:start_idx - boundary_size].obj)
                if start_idx >= 0:
                    if self._fh is not None:
                        self._fh.close()
                        self._fh = None
                    self._data_end_marker = bytearray()
                    self._state = _States.DATA_END
                else:
                    # proceed to the next chunk
                    break
            elif self._state == _States.DATA_END:
                ctr = 0
                while start_idx < len(mv_chunk):
                    self._data_end_marker.append(mv_chunk[start_idx])
                    start_idx += 1
                    if len(self._data_end_marker) == 2 and self._data_end_marker == b'\r\n':
                        # we still have more fields to process
                        self._cd_str = b''
                        self._state = _States.CD_HDR
                        # proceed to the next iteration in this chunk
                        break
                    elif len(self._data_end_marker) == 4:
                        if self._data_end_marker == b'--\r\n':
                            # done
                            return True
                        else:
                            # consider the data invalid
                            return False

        # save the old chunk for truncated boundary
        self._old_chunk = mv_chunk
