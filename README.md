[README.md](https://github.com/user-attachments/files/32100472/README.md)
# Sequence Toolkit

[**English**](README.md) | [中文](README.zh-CN.md)

A dependency-free Windows GUI for merging, converting, renaming and batch-downloading FASTA and GenBank sequences.

Sequence Toolkit gathers the small, repetitive and easily-mistaken chores of sequence data curation behind one window: combining files whose extensions are inconsistent, converting GenBank to FASTA, normalising sequence names for downstream tools, and retrieving sequences from NCBI by species or genus. It is distributed as a single executable of roughly 10 MB — **no Python installation, no third-party packages and no command line required**.

## Features

| Tab | What it does |
|---|---|
| **Merge / Convert** | Combine many FASTA or GenBank files into one output file, or convert **each input file into its own output file**. Formats are recognised from file content, not from the extension. |
| **Rename / Split** | Rewrite `>` header lines with one of three naming rules. Optionally split a multi-record file into individual files, or rename existing files on disk from their contents. |
| **Search & Batch download** | Query NCBI Nucleotide by species or genus, filter by sequence length, complete-genome status and RefSeq, then download the records you select. Export the resulting accession numbers as `.txt` or `.csv`. |
| **Download by accession** | Paste accession numbers, load them from a text file, or extract them automatically from FASTA/GenBank files you already have. |
| **Settings** | NCBI e-mail and API key, HTTP proxy, default output directory, custom file extensions, FASTA line width. |

## Naming rules

| Rule | Example |
|---|---|
| Accession | `ON929859.1` |
| Species | `Salsola_pellucida` |
| Accession\_Species | `ON929859.1_Salsola_pellucida` |

Spaces are always replaced with `_`. **Serial numbers (`_1`, `_2`) are appended only when the resulting file names would otherwise collide.** In practice that means the Accession and Accession\_Species rules normally add no suffix (the accession is already unique), while the Species rule adds one when a species occurs more than once — which is exactly the case where omitting it would produce two identical file names.

## Merge / Convert: two output modes

| Output mode | Result | Output selector |
|---|---|---|
| Combine into a single file *(default)* | All inputs become **one** file | choose an output **file** |
| **One output file per input file** | One input file → one output file | choose an output **directory** |

In per-file mode:

- the **output file name is the original file stem** plus the target extension: `sample.gbk` → `sample.fasta`, and `sample.gbk.gz` → `sample.fasta` (both suffix layers are stripped — never `sample.gbk.fasta`)
- sequence names **inside** the file follow the tab's naming rule
- each input file is processed independently: serial numbers and de-duplication are scoped **within a single file**, so one species appearing in two different files does not produce spurious suffixes
- a file containing only `CONTIG` records produces **no empty output file**; it is reported and skipped
- a file that cannot be read or written is logged and skipped — **the batch is never aborted**

Input extensions: `.fasta` `.fa` `.fna` `.fas` `.ffn` `.frn` `.fsa` `.seq` for FASTA and `.gb` `.gbk` `.genbank` `.gbff` `.gp` for GenBank, plus transparent `.gz` decompression. Output uses `.fasta` and `.gb`. Custom extensions can be added in Settings.

## Search, download and accession export

Search uses the NCBI E-utilities (`esearch` with history, `esummary`, `efetch`). Species names are matched as quoted organism terms; genus names are matched unquoted so that every species in the genus is covered. "Complete genome only" is a **local** filter on the definition line, because NCBI exposes no reliable server-side field for it.

Downloads obey NCBI's rate limits (3 requests/second, or 10 with an API key), retry transient failures, and continue past individual failures. If a batch request fails, each accession is retried individually so that one bad accession cannot lose the rest.

Results can be exported as accession lists — one per line in `.txt`, or `.csv` with the same columns as the result table (accession, length, organism, definition, date, source). Rows you tick are exported; if you tick none, the whole displayed table is exported and the log says so.

## Data-integrity guarantees

These are the deliberate design decisions that make the tool safe to point at a directory of real data:

- **Annotations survive conversion.** A GenBank record is carried as its original text block, so `FEATURES` (CDS, rRNA, tRNA, …) is preserved byte for byte through merging and format conversion. Renaming touches only the `LOCUS` name column.
- **No output file is ever overwritten silently.** A target that already exists is skipped when its content is byte-identical, and otherwise receives a numeric suffix; the actual path written is always logged.
- **Nothing is dropped quietly.** Unassembled `CONTIG` records, unreadable files, unparsable headers and blocked writes all appear in an exportable exception list with file, line number and the name finally applied.
- **Writes are atomic.** Output is staged and moved into place, so a crash cannot leave a truncated file that a later run would mistake for a complete one.
- **Encoding damage is reported, not hidden.** Non-UTF-8 input raises an explicit encoding warning instead of being silently mangled.
- **Non-Latin paths work.** Chinese directory and file names are a first-class tested scenario.

## Quick start

1. Download `Sequence工具箱.exe` from the [Releases](../../releases) page and double-click it.
2. Open the **Settings** tab and fill in two fields:
   - **NCBI e-mail** — required by NCBI; requests without one may be throttled.
   - **Proxy** — optional, but recommended in mainland China, where direct connections to NCBI frequently time out (for example `http://127.0.0.1:7897` for a default Clash installation).

> If double-clicking does nothing, antivirus software has most likely quarantined the executable. Add it to the allow-list, or build it from source as described below.

## Run from source

Requires Python 3.12 or later with Tkinter (included in the official Windows installer).

```bash
python -m pip install -r requirements.txt
python main.py
```

## Build a single-file executable

```bash
python -m pip install -r requirements.txt
python -m PyInstaller --clean --noconfirm build.spec
```

The result is `dist/序列工具箱.exe`. Removing the `onefile` options from `build.spec` produces a faster-starting folder build instead.

## Tests

```bash
python -m pytest -v
```

442 automated tests cover the parsers, the naming engine, the orchestration layer, the NCBI client (offline, with injected transports) and the GUI widgets. No test performs real network I/O or real sleeps.

## Known limitations

- **The GenBank `LOCUS` name field is only 16 columns wide.** Longer names cannot be represented there, so the original `LOCUS` name is kept unchanged (truncating it would break column alignment and downstream fixed-width parsers) and the intended name is written to the log instead. FASTA output has no such restriction.
- **Unassembled records** (`CONTIG` without `ORIGIN`) cannot yield a sequence; they are listed in the exception list rather than discarded.
- **"Complete genome only" is a local filter** based on definition-line keywords, not an NCBI field.
- **Metadata is fetched for the first 500 search hits.** Narrow the filters if a query returns more; the interface tells you when this happens.
- **Downloads are sequential, not concurrent.** NCBI's rate limit, not local concurrency, is the bottleneck, and sequential requests are far less likely to be throttled.
- The user interface is in Chinese.

## Repository layout

```
main.py                  entry point
build.spec               PyInstaller configuration
seq_toolkit/
  model.py               SequenceRecord — the single data contract
  textio.py              UTF-8 / BOM / .gz text opening
  format_detect.py       format detection (content before extension)
  fasta_io.py            FASTA reading and writing
  genbank_io.py          GenBank reading and writing (raw block preserved)
  naming.py              naming-rule engine (pure functions)
  pipeline.py            merge / convert / split / disk-rename orchestration
  ncbi.py                E-utilities client
  settings.py            configuration persistence
  applog.py              run log and exception list
  gui/                   Tkinter interface
tests/                   pytest suite
docs/acceptance.md       end-to-end acceptance record
docs/superpowers/        design specification and implementation plan
```

## Contributing

Issues and pull requests are welcome. Please run `python -m pytest` before opening a pull request — every change in this project is expected to keep the suite green.

## License

[MIT](LICENSE) © 2026 Mark

Sequence Toolkit has **no third-party runtime dependencies** — only the Python standard library. Sequence data downloaded through the tool remains subject to the terms of NCBI and of the original data submitters.
