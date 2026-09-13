# Sequence Toolkit

[**English**](README.md) | [中文](README.zh-CN.md)

A dependency-free Windows GUI for merging, converting, renaming and batch-downloading FASTA and GenBank sequences.

Sequence Toolkit gathers the small, repetitive and easily-mistaken chores of sequence data curation behind one window: combining files whose extensions are inconsistent, converting GenBank to FASTA, normalising sequence names for downstream tools, retrieving sequences from NCBI by species or genus, cleaning a species list through the TNRS service, and building a phylogenetic tree from that list. It is distributed as a single executable of roughly 10 MB — **no Python installation, no third-party packages and no command line required**. (Tree generation is the one feature that can use an external program, R — optional, and only if you want that tab.)

## Features

| Tab | What it does |
|---|---|
| **Merge / Convert** | Combine many FASTA or GenBank files into one output file, or convert **each input file into its own output file**. Formats are recognised from file content, not from the extension. |
| **Rename / Split** | Rewrite `>` header lines with one of three naming rules. Optionally split a multi-record file into individual files, or rename existing files on disk from their contents. |
| **Search & Batch download** | Query NCBI Nucleotide by species or genus, filter by sequence length, complete-genome status and RefSeq, then download the records you select. Export the resulting accession numbers as `.txt` or `.csv`. |
| **Download by accession** | Paste accession numbers, load them from a text file, or extract them automatically from FASTA/GenBank files you already have. |
| **Name cleaning (TNRS)** | Resolve a list of scientific names through the TNRS service (WCVP + WFO) and get the accepted name, match status and source database for each one. Export the result as CSV, or write the accepted names back into FASTA/GenBank files. |
| **Phylogenetic tree** | Turn a species list into a Newick tree file with R + V.PhyloMaker2 (TPL / LCVP / WP megatrees, binding scenarios S1–S3) and preview it in the window. R is an **optional** external dependency — see below. |
| **Settings** | NCBI e-mail and API key, HTTP proxy, default output directory, optional Rscript path, custom file extensions, FASTA line width. |

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

## Name cleaning and phylogeny

### Name cleaning (TNRS)

Paste a list of scientific names into the **Name cleaning** tab and press **Start cleaning** (开始清洗) to obtain the accepted name, the match status and the source database of every name. The result can be exported as CSV, and the accepted names can be written back into FASTA / GenBank files.

- Uses the online TNRS service (`https://tnrsapi.xyz/tnrs_api.php`). One request carries at most 5,000 names; longer lists are split into batches automatically. The default nomenclatural sources are WCVP + WFO.
- **Unmatched names never disappear**: they stay in the table with the status "未匹配" (unmatched) and are summarised **below** the result list (the summary line and the warning note are packed under the result table).
- The match mode is either `best` (best match only, the default) or `all` (every candidate). With `all` a single name may produce several rows, and the interface states "N 个名称 → M 行结果" (N names → M result rows).
- Writing names back **never overwrites the input file**: the result goes to the directory you choose with a `_cleaned` suffix added (`样本.fasta` → `样本_cleaned.fasta`).
- **The 「名录来源」/「匹配模式」 dropdowns last for the current session only**: they are read once while the panel is built and are **not written back** to `settings.json`, so restarting the program returns to the last saved values. To pin a source or a match mode at start-up, edit `%APPDATA%\seq_toolkit\settings.json` (`tnrs_sources` / `tnrs_matches`) directly.

### Phylogenetic tree generation (V.PhyloMaker2)

Paste the scientific names of your species into the **Phylogenetic tree** tab, pick a nomenclature system and a binding scenario, and press **Generate tree** (生成进化树) to obtain a Newick tree file together with an in-window preview. **The names are all you need** — the genus and family are filled in by the program.

- Requires R and the R package V.PhyloMaker2 on your own machine (optional external dependencies, **not bundled** with this program):
  1. Install R: <https://cran.r-project.org/bin/windows/base/> (the default installation is fine; no administrator rights are needed)
  2. In R, run `install.packages("remotes")` and then `remotes::install_github("jinyizju/V.PhyloMaker2")`
  3. Back in this program, enter the path to `Rscript.exe` on the **Settings** tab, or press **Detect R** (检测 R 环境) to find it automatically
- The nomenclature system is one of **TPL** (The Plant List, 74,529 species, the default), **LCVP** (73,420 species) or **WP** (World Plants, 72,570 species) — the three megatrees bundled with V.PhyloMaker2.
- The binding scenarios S1/S2/S3 mean "bind to the genus node only / random resolution within the family / random resolution within the genus"; the default is S3.
- **Species that cannot be bound to the megatree are listed explicitly** (a misspelling, or a name the catalogue does not contain), so they never disappear unnoticed.
- The first run has to load the megatree: about 17 seconds for 7 species in practice, and more species take longer.
- **The 「命名系统」/「绑定场景」 dropdowns last for the current session only**: they are read once while the panel is built and are **not written back** to `settings.json`, so restarting the program returns to the last saved values. To pin a system or a scenario at start-up, edit `%APPDATA%\seq_toolkit\settings.json` (`phylo_system` / `phylo_scenario`) directly.

### Known limitations of these two features

- **Tree generation depends on R and V.PhyloMaker2 installed locally.** Both are **optional external dependencies and are not bundled into the executable**; without them the other six tabs work exactly as before. When something is missing the program shows a copy-pasteable three-step installation guide (install R → `install.packages("remotes")` + `remotes::install_github("jinyizju/V.PhyloMaker2")` → enter the `Rscript.exe` path on the Settings tab or press **Detect R**), never an exception stack. The Settings tab additionally offers a **Copy install guide** button, because those lines have to be pasted into R.
- **The nomenclature systems are the three megatrees bundled with V.PhyloMaker2 — TPL / LCVP / WP** (species counts above) — and **not** APG III or APG IV. The package offers no such option, and the interface deliberately does not pretend otherwise.
- **The binding scenarios S1 / S2 / S3 decide where an unlisted species is attached to the megatree**: S1 binds to the **genus node** only, S2 uses random resolution **within the family**, S3 uses random resolution **within the genus** (the default). For a species the megatree actually contains all three give the same tree; the difference only shows up for species that need a fallback to genus or family level.
- **Species that fail to bind are reported explicitly**, together with "input N species / M tips in the tree", instead of silently losing a few species and leaving the user thinking the run succeeded — the "nothing is dropped quietly" rule applied to tree building. R itself prints **two** lines — `[1] "Note: 1 taxa fail to be binded to the tree,"` followed by one line per dropped species (measured on R 4.6.1: `[1] "Xyzzy_foobar"`) — and drops the species; this program catches both lines and reports the list in the window and in the log (as a WARN).
- **The first run loads a megatree** (more than 70,000 species), which took about 17 seconds for 7 species in practice; hundreds or thousands of species can take minutes. Tree building therefore runs on a background thread, can be cancelled, and times out after 600 seconds.
- **Name write-back supports uncompressed FASTA / GenBank only**: `.gz` files and non-UTF-8 files (GBK, common on Chinese Windows, for instance) are **rejected explicitly**, with a message telling you to decompress or transcode first. This is a deliberate safety trade-off: reading those files with decoding errors ignored raises nothing and would simply write a corrupted `_cleaned` file that *looks* like a success — making the user take one extra step is much better than emitting a damaged file.
- **Rows whose status is "partial match" also take part in name write-back**: the specification only excludes "unmatched", so a partial match (score below 1) has its accepted name written into the file as well. Before writing, the interface says how many such rows there are, so that "why was this name replaced by something that is not exactly it?" never comes as a surprise.

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

556 automated tests cover the parsers, the naming engine, the orchestration layer, the NCBI client (offline, with injected transports), the TNRS client, the R runner and the GUI widgets. **555 of them pass**; the single failure is a pre-existing timing case, `tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock` (floating-point residue while reconstructing the request timeline), which this project has decided to leave unfixed and which has nothing to do with these features. No test performs real network I/O or real sleeps: TNRS requests go through an injected stand-in and R runs through an injected runner. The real-environment acceptance record (including the runs against R 4.6.1 and V.PhyloMaker2) lives in `docs/acceptance.md`.

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
  tnrs.py                name cleaning (TNRS request building, batching, parsing, CSV, write-back)
  phylo.py               tree generation (Rscript detection, R script rendering, unbound-species parsing, Newick parsing)
  settings.py            configuration persistence
  applog.py              run log and exception list
  gui/                   Tkinter interface (tab_tnrs.py, tab_phylo.py, tree_canvas.py)
tests/                   pytest suite
docs/acceptance.md       end-to-end acceptance record (28 items plus 12 for features 7 and 8)
docs/superpowers/        design specification and implementation plan
```

## Contributing

Issues and pull requests are welcome. Please run `python -m pytest` before opening a pull request — every change is expected to keep the tests related to it green and the number of passing tests from falling (the one known `test_ncbi` failure noted under **Tests** excepted).

## License

[MIT](LICENSE) © 2026 Mark

Sequence Toolkit has **no third-party runtime dependencies** — only the Python standard library. Sequence data downloaded through the tool remains subject to the terms of NCBI and of the original data submitters.
