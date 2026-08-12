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

    def feed(self, chunk):
        self._buffer += chunk
        lines = self._buffer.splitlines()
        self._buffer = ""
        values = []
        for line in lines:
            self._line_number += 1
            if line.strip():
                values.append(json.loads(line))
        return values

    def finalize(self):
        if not self._buffer.strip():
            return []
        self._line_number += 1
        value = json.loads(self._buffer)
        self._buffer = ""
        return [value]
