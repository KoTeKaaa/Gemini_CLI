# Read just the part of a document you need

[Русский](../documents.md) · [English](documents.md) · [Home](../../README.en.md)

Use `/doc help` for examples in the client. Document ranges work in Local and
Remote; extraction always happens on your computer. Original binary bytes stay
local. The selected text enters the conversation when you send the draft.

```text
@report.pdf#pages=1-3
@notes.docx#paragraphs=2-5
@notes.docx#sections=1
@notes.docx#tables=1
@data.csv#cells=A1:C10&encoding=cp1251&delimiter=%3B
@book.xlsx#sheets=list
@book.xlsx#sheet=Data&cells=A1:C10
```

The model can request the same operation with `read_document(filepath=..., selection=...)`
after your approval. For example, pass `selection="pages=1-3"` for a PDF.
Use URL encoding in selectors when a sheet name or delimiter needs it.
Do not use text-file `:line` syntax for binary documents or omit their selection.

## What each format returns

- **PDF:** selected page text with page numbers. Scans without text and encrypted
  PDFs are unsupported; no OCR runs. Layout and reading order may be incomplete.
- **DOCX:** selected paragraphs, Word sections or tables with stable positions.
  This does not reproduce the full page layout, images, headers or footnotes.
- **CSV:** selected cells with explicit or detected delimiter; UTF-8/BOM, UTF-16
  and cp1251 encodings. Header rows are included only when selected.
- **XLSX:** a named worksheet and cells, or an explicit sheet list. Formula text
  and saved cached values are separate. A cache may be absent or stale; `null`
  does not mean zero. Dates and number formats are not rendered or recalculated.

## Limits and privacy

Inputs are limited to 4 MiB. ZIP entries, expansion and compression ratios are
bounded; unsafe members, macros and external relationships are rejected. The
worker has time, memory and output limits. PDF selection is limited to 10 pages;
grid ranges to 100 rows and 200 cells. Large selections should be split up.

The result identifies its source, positions and any truncation or partial
extraction. An unsupported or damaged file is an error, not a successful read.
No macros, formulas, external links or PDF helper programs are executed.

Use `/attachments`, `/show N`, `/edit N` and `/remove N` to inspect the unsent draft.
A denied read or a file changed since approval does not silently replace it.
Extracted tool responses are redacted from permanent history. Text you explicitly
attach to a user message is part of that message and can be saved with the chat.
