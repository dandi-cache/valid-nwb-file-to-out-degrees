# DANDI Cache: `valid-nwb-file-to-out-degrees`

A mapping from the content ID of every valid HDF5 NWB file on the DANDI archive to out-degree statistics of that file's internal object hierarchy.

The set of valid NWB files is taken from the [`content-id-to-valid-nwb-file`](https://github.com/dandi-cache/content-id-to-valid-nwb-file) cache, restricted to the entries it marked `true` and further restricted to those stored as a single HDF5 blob (Zarr assets have no internal HDF5 group/dataset hierarchy and are skipped). Each such file is streamed directly from the public DANDI S3 bucket with [remfile](https://github.com/flatironinstitute/remfile) and read with [h5py](https://www.h5py.org/).

## What is computed

An NWB file's own group/dataset structure is used directly as a rooted tree:

- **Internal nodes** are groups that contain at least one child.
- **Leaves** are nodes with no children: every dataset, plus any empty group.
- A node's **out-degree** is its number of direct children (subgroups + datasets).

For every internal node (out-degree $\geq 1$; the root counts when it has children), the out-degree is collected, and the following summary statistics are computed over that list:

- `n_internal_nodes`: the number of internal nodes.
- `mean_out_degree`: the mean out-degree.
- `max_out_degree`: the maximum out-degree.
- `variance_out_degree`: the population variance of the out-degrees.
- `median_out_degree`: the median out-degree.

Leaves (out-degree 0) are excluded from the statistics. A file whose root has no children (no internal nodes at all) reports zeroed-out statistics, with `median_out_degree` as `null`.

Each line of the derivatives is a JSON object of the form:

```json
{"<content_id>": {"n_internal_nodes": <int>, "mean_out_degree": <float>, "max_out_degree": <int>, "variance_out_degree": <float>, "median_out_degree": <float or null>}}
```

Updated frequently.

Primarily for use by developers.



## One-time use

`dist` publishes each output as a [Zarr](https://zarr.dev/) store: the cache itself is `derivatives/valid_nwb_file_to_out_degrees.zarr/`.
A store is one array of [JSON Lines](https://jsonlines.org/) text cut into chunk files, each holding whole lines and gzip-compressed.
It can be read with the standard library alone, or opened remotely with any Zarr library.

### Python API (recommended)

The chunk files are gzip-compressed [JSON Lines](https://jsonlines.org/): list them, then read them in order as you would any JSONL files.

```python
import gzip, json, urllib.request

chunks = "https://api.github.com/repos/dandi-cache/valid-nwb-file-to-out-degrees/contents/derivatives/valid_nwb_file_to_out_degrees.zarr/stream/c?ref=dist"
files = sorted((entry["download_url"] for entry in json.load(urllib.request.urlopen(chunks))), key=lambda url: int(url.rsplit("/", 1)[1]))
valid_nwb_file_to_out_degrees = {key: value for url in files for line in gzip.decompress(urllib.request.urlopen(url).read()).decode().splitlines() if line for key, value in json.loads(line).items()}
```

Each line is a single-entry mapping of `{"<content_id>": <out_degree_statistics>}`.

An entry is not filed under its key: the chunks hold the entries in the order they were recorded, so looking up one means reading through them.
To look up many, read it once as above, or clone the `derivatives` branch.

### Remote Zarr store

Anything that opens Zarr can open the store over HTTP, reading only the chunks it needs.
The group's `zarr.json` carries the array's metadata, so opening it takes one request:

```bash
pip install "zarr>=3" fsspec aiohttp
```

```python
import json

import zarr

url = "https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-out-degrees/refs/heads/dist/derivatives/valid_nwb_file_to_out_degrees.zarr"
stream = zarr.open_group(url, mode="r")["stream"]
print(stream.shape, stream.chunks)  # Bytes in all, and bytes per chunk.

# The first chunk, fetched and decompressed on its own: whole lines, each `{"<key>": <value>}`.
first_chunk = stream[: stream.chunks[0]].tobytes().decode("utf-8")
for line in first_chunk.splitlines():
    if line.strip():
        print(json.loads(line))
        break
```

Reading `stream[:]` returns the whole text; to read it in pieces, step through it by `stream.chunks[0]`, as each chunk is fetched whole.

### Save to file

A raw URL cannot be listed, so to fetch every chunk at once clone the `dist` branch, which holds nothing else:

```bash
git clone --branch dist --depth 1 https://github.com/dandi-cache/valid-nwb-file-to-out-degrees.git
```



## Repeated use

If you plan on using this cache regularly, clone the `derivatives` branch of this repository:

```bash
git clone --branch derivatives https://github.com/dandi-cache/valid-nwb-file-to-out-degrees.git
```

Or, if you prefer [DataLad](https://www.datalad.org/):

```bash
datalad clone https://github.com/dandi-cache/valid-nwb-file-to-out-degrees.git --branch derivatives
```

Then set up a CRON on your system to pull the latest version of the cache at your desired frequency.

For example, through `crontab -e`, add:

```bash
0 0 * * * git -C /path/to/valid-nwb-file-to-out-degrees pull
```

This will minimize data overhead by only loading the most recent changes.

Each output is a store on the `derivatives` branch, where it is the whole log, uncompacted, and plain text:

```python
import json, pathlib

chunks = sorted(pathlib.Path("valid-nwb-file-to-out-degrees/derivatives/valid_nwb_file_to_out_degrees.zarr/stream/c").iterdir(), key=lambda path: int(path.name))
valid_nwb_file_to_out_degrees = {key: value for chunk in chunks for line in chunk.read_text().splitlines() if line for key, value in json.loads(line).items()}
```
