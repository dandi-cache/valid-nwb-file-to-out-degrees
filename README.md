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

If you only plan to use this cache infrequently or from disparate locations, you can directly download the latest version of the cache as a compressed [JSON Lines](https://jsonlines.org/) file from the `dist` branch:

### Python API (recommended)

```python
import gzip
import json

import requests

url = "https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-out-degrees/refs/heads/dist/derivatives/valid_nwb_file_to_out_degrees.jsonl.gz"
response = requests.get(url)
lines = gzip.decompress(data=response.content).decode("utf-8").splitlines()
valid_nwb_file_to_out_degrees = [json.loads(line) for line in lines]
```

Each line is a single-entry mapping of `{"<content_id>": <out_degree_statistics>}`.

### Save to file

```bash
curl https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-out-degrees/refs/heads/dist/derivatives/valid_nwb_file_to_out_degrees.jsonl.gz -o valid_nwb_file_to_out_degrees.jsonl.gz
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
