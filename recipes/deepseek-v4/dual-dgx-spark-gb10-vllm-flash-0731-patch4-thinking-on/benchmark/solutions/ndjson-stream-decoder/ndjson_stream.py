"""Incremental newline-delimited JSON decoding."""

import json


class NDJSONError(ValueError):
    def __init__(self, line_number, message):
        self.line_number = line_number
        self.message = message
        super().__init__(f"line {line_number}: {message}")


class NDJSONDecoder:
    def __init__(self):
        self._buffer = ""
        self._line_number = 0
        self._finalized = False

    def _decode_line(self, line):
        if not line.strip():
            return []
        try:
            return [json.loads(line)]
        except json.JSONDecodeError as exc:
            raise NDJSONError(self._line_number, exc.msg) from exc

    def feed(self, chunk):
        if self._finalized:
            raise RuntimeError("decoder is finalized")
        if not isinstance(chunk, str):
            raise TypeError("chunk must be str")
        self._buffer += chunk
        values = []
        while True:
            newline = self._buffer.find("\n")
            if newline < 0:
                break
            line = self._buffer[:newline]
            self._buffer = self._buffer[newline + 1 :]
            if line.endswith("\r"):
                line = line[:-1]
            self._line_number += 1
            values.extend(self._decode_line(line))
        return values

    def finalize(self):
        if self._finalized:
            return []
        self._finalized = True
        if not self._buffer:
            return []
        line = self._buffer
        self._buffer = ""
        self._line_number += 1
        return self._decode_line(line)
