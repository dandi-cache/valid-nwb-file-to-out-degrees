import argparse
import itertools
import json
import pathlib

import h5py
import numpy
import remfile

# Testing mode processes only this many items and writes to its own designated file
# (`derivatives/testing.jsonl`), leaving the real cache untouched.
_TESTING_LIMIT = 10
_CACHE_FILE_NAME = "valid_nwb_file_to_out_degrees.jsonl"
_TESTING_FILE_NAME = "testing.jsonl"

# The input is the `content-id-to-valid-nwb-file` cache, registered as an input subdataset.
_INPUT_FILE_PATH = (
    pathlib.Path("sourcedata") / "content-id-to-valid-nwb-file" / "derivatives" / "content_id_to_valid_nwb_file.jsonl"
)

# The public DANDI archive S3 bucket. Every asset is content-addressed, so each valid NWB
# file is reachable directly from its content ID without consulting the DANDI API. Only the
# HDF5 blob layout is in scope for this cache: `blobs/<c[:3]>/<c[3:6]>/<content_id>`. Zarr
# assets (no such blob) are skipped, since a Zarr store has no internal HDF5 group/dataset
# hierarchy to compute out-degrees over.
_BLOB_URL_TEMPLATE = "https://dandiarchive.s3.amazonaws.com/blobs/{prefix}/{infix}/{content_id}"


def _load_content_id_to_validity(file_path: pathlib.Path) -> dict:
    """Load the `{content_id: bool}` mapping from the input JSONL, or an empty dict if missing."""
    records: dict = {}
    if not file_path.exists():
        return records
    with file_path.open(mode="r") as file_stream:
        for line in file_stream:
            if line.strip():
                records.update(json.loads(line))
    return records


def _load_previous_cache(file_path: pathlib.Path) -> dict:
    """Load the previously computed `{content_id: out_degree_statistics}` mapping (empty on bootstrap)."""
    records: dict = {}
    if not file_path.exists():
        return records
    with file_path.open(mode="r") as file_stream:
        for line in file_stream:
            if line.strip():
                records.update(json.loads(line))
    return records


def _write_cache(file_path: pathlib.Path, records: dict) -> None:
    """Write the `{content_id: out_degree_statistics}` mapping, one sorted content ID per line."""
    with file_path.open(mode="w") as file_stream:
        file_stream.writelines(f"{json.dumps({content_id: records[content_id]})}\n" for content_id in sorted(records))


def _internal_node_out_degrees(root_group: h5py.Group) -> list[int]:
    """
    Collect the out-degree of every internal node in an HDF5 group/dataset hierarchy.

    The file's own group/dataset structure is the tree: groups are internal nodes and any
    node without children is a leaf (every dataset, plus any empty group). A node's out-degree
    is its number of direct children (subgroups + datasets). Only internal nodes (out-degree
    >= 1) contribute an entry; leaves contribute nothing.

    The walk is done explicitly with `group.keys()` / `isinstance` checks (not `visititems`)
    so each group's own child count is available, including empty groups, which `visititems`
    never visits as a group in its own right. Soft links (and any other route back to an
    already-visited group) are guarded against via the group's on-disk object address, so a
    link cycle is walked at most once instead of recursing forever.
    """
    out_degrees: list[int] = []
    visited_addresses: set[int] = set()

    def _walk(group: h5py.Group) -> None:
        address = h5py.h5o.get_info(group.id).addr
        if address in visited_addresses:
            return
        visited_addresses.add(address)

        child_names = list(group.keys())
        if not child_names:
            return  # An empty group is a leaf; it contributes no out-degree entry.

        out_degrees.append(len(child_names))
        for child_name in child_names:
            child = group[child_name]
            if isinstance(child, h5py.Group):
                _walk(child)
            # `h5py.Dataset` children are always leaves; nothing further to walk.

    _walk(root_group)
    return out_degrees


def _out_degree_statistics(out_degrees: list[int]) -> dict:
    """
    Summary statistics of a list of internal-node out-degrees.

    Handles the degenerate case of no internal nodes (e.g. a root with no children) by
    returning zeroed-out statistics, with `median_out_degree` as `None` since there is no
    value to report.
    """
    if not out_degrees:
        return {
            "n_internal_nodes": 0,
            "mean_out_degree": 0.0,
            "max_out_degree": 0,
            "variance_out_degree": 0.0,
            "median_out_degree": None,
        }

    out_degree_array = numpy.array(out_degrees, dtype=float)
    return {
        "n_internal_nodes": len(out_degrees),
        "mean_out_degree": float(out_degree_array.mean()),
        "max_out_degree": int(out_degree_array.max()),
        "variance_out_degree": float(out_degree_array.var()),  # population variance (ddof=0)
        "median_out_degree": float(numpy.median(out_degree_array)),
    }


def compute_out_degree_statistics(url: str) -> dict:
    """Stream an HDF5 file from `url` and compute the out-degree statistics of its object hierarchy."""
    remote_file = remfile.File(url=url)
    with h5py.File(remote_file, mode="r") as h5py_file:
        out_degrees = _internal_node_out_degrees(root_group=h5py_file)
    return _out_degree_statistics(out_degrees=out_degrees)


def _compute_out_degree_statistics(content_id: str) -> dict:
    """Compute the out-degree statistics of the valid HDF5 NWB file identified by `content_id`."""
    blob_url = _BLOB_URL_TEMPLATE.format(prefix=content_id[:3], infix=content_id[3:6], content_id=content_id)
    return compute_out_degree_statistics(url=blob_url)


def _run(base_directory: pathlib.Path, testing: bool, limit: int | None) -> None:
    content_id_to_validity = _load_content_id_to_validity(file_path=base_directory / _INPUT_FILE_PATH)
    # Only the assets the upstream cache marked valid ('true') are processed.
    valid_content_ids = {content_id for content_id, is_valid in content_id_to_validity.items() if is_valid is True}

    derivatives_directory = base_directory / "derivatives"
    derivatives_directory.mkdir(parents=True, exist_ok=True)
    cache_file_path = derivatives_directory / (_TESTING_FILE_NAME if testing else _CACHE_FILE_NAME)
    valid_nwb_file_to_out_degrees = _load_previous_cache(file_path=cache_file_path)

    # Already-computed content IDs are exactly the keys already in the output, so re-runs skip
    # them and only pick up content IDs newly marked valid upstream.
    content_ids_to_process = sorted(valid_content_ids - valid_nwb_file_to_out_degrees.keys())

    # A testing run caps the batch tightly; otherwise the optional `--limit` bounds a single
    # run because streaming and walking each file is heavy.
    effective_limit = _TESTING_LIMIT if testing else limit
    content_ids_to_process = list(itertools.islice(content_ids_to_process, effective_limit))

    for content_id in content_ids_to_process:
        try:
            out_degree_statistics = _compute_out_degree_statistics(content_id=content_id)
        except Exception as exception:
            # A content ID with no HDF5 blob is a Zarr asset (out of scope for this cache), and
            # a content ID that was already validated upstream failing here is almost always
            # transient (network). Either way, skip it and leave it for a later run to retry
            # rather than recording a wrong value.
            print(f"Skipping `{content_id}`: {type(exception).__name__}: {exception}", flush=True)
            continue
        valid_nwb_file_to_out_degrees[content_id] = out_degree_statistics

    _write_cache(file_path=cache_file_path, records=valid_nwb_file_to_out_degrees)


if __name__ == "__main__":
    default_base_directory = pathlib.Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Update the valid-nwb-file-to-out-degrees DANDI cache.")
    parser.add_argument(
        "--base-directory",
        type=pathlib.Path,
        default=default_base_directory,
        help=(
            "The directory containing the `sourcedata` and `derivatives` directories. "
            "Set to the mounted dataset path when run inside the pipeline container; "
            "defaults to the repository root."
        ),
    )
    parser.add_argument(
        "--testing",
        action="store_true",
        help=(
            f"Run in testing mode: process only the first {_TESTING_LIMIT} items and write "
            f"`derivatives/{_TESTING_FILE_NAME}` instead of the real cache, leaving it "
            "untouched. Omit for a complete update."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of newly valid content IDs to process in this run.",
    )
    args = parser.parse_args()

    _run(base_directory=args.base_directory, testing=args.testing, limit=args.limit)
