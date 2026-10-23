"""Ограничивающий UTF-8 decoder через публичную настройку SDK encoding."""

import codecs

MAX_LINE_BYTES = 262144
ENCODING = 'gemini_mcp_utf8'


class BoundedUTF8Decoder(codecs.getincrementaldecoder('utf-8')):
    def __init__(self, errors='strict'):
        super().__init__(errors)
        self.line_bytes = 0

    def decode(self, value, final=False):
        # Count before decoding or returning text to the SDK stdout accumulator.
        pieces = bytes(value).split(b'\n')
        for index, piece in enumerate(pieces):
            self.line_bytes += len(piece)
            if self.line_bytes > MAX_LINE_BYTES:
                raise UnicodeError('MCP: входная строка превышает лимит')
            if index < len(pieces) - 1:
                self.line_bytes = 0
        return super().decode(value, final)

    def reset(self):
        super().reset()
        self.line_bytes = 0


def _lookup(name):
    if name == ENCODING:
        utf8 = codecs.lookup('utf-8')
        return codecs.CodecInfo(name=ENCODING, encode=utf8.encode, decode=utf8.decode,
            incrementalencoder=utf8.incrementalencoder, incrementaldecoder=BoundedUTF8Decoder,
            streamreader=utf8.streamreader, streamwriter=utf8.streamwriter)


codecs.register(_lookup)
