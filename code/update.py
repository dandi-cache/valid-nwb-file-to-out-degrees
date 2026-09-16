"""Out-degree statistics of every valid NWB file's internal hierarchy.

The file's own structure is the tree: groups are internal nodes, and every dataset plus every
childless group is a leaf. A node's out-degree is its number of direct children, and only internal
nodes contribute one, so the statistics below describe how wide the tree is at the places it
branches at all.

Two things this cache does that its siblings do not, both preserved from what it has published:

- `LINKS_FOLLOWED`, so the hierarchy is walked as it is named. Every entry of a group is a child
  of it, whatever kind of link put it there, and a group already walked is not walked again, which
  is what stops a link cycle. The default policy would instead skip soft links entirely and give a
  different, smaller tree.
- HDF5 only. `layout` is named rather than probed, exactly as this cache has always done: it reads
  the content-addressed blob directly, so a Zarr asset fails to open and is left for a later run
  rather than recorded. A Zarr store has no link structure to compare against anyway.

Everything shared with the other caches -- the argument parsing, the logging, the batch cap, the
error logs, the output paths, testing mode, and the structural walk itself -- comes from
`dandi_cache_utils`, which the runtime image carries.
"""

import dandi_cache_utils as dandi_cache
import numpy


def out_degree_statistics(out_degrees: list[int], /) -> dict:
    """Summary statistics of a list of internal-node out-degrees.

    A root with no children has no internal nodes at all, which is not an error but has no average
    to report, so `median_out_degree` is `None` there rather than a number standing in for one.
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


def compute_out_degree_statistics(content_id, item) -> dict:
    """Walk one HDF5 asset, resolved straight from its content ID, and summarize its branching."""
    item.stage = "reading the NWB file"
    structure = dandi_cache.nwb.walk_structure(
        content_id,
        layout=dandi_cache.nwb.HDF5,
        links=dandi_cache.nwb.LINKS_FOLLOWED,
    )
    return out_degree_statistics(structure.out_degrees)


def main() -> None:
    dataset, arguments = dandi_cache.open_dataset()

    # Only the assets the upstream cache marked valid are measured.
    validity = dataset.read_input()
    valid_content_ids = [content_id for content_id, is_valid in validity.items() if is_valid is True]

    dandi_cache.run_incremental_update(
        dataset,
        candidates=valid_content_ids,
        process=compute_out_degree_statistics,
        limit=dandi_cache.effective_limit(testing=dataset.testing, limit=arguments.limit),
        # These files were already opened successfully upstream, so a failure here is almost always
        # transient. Leave the item for a later run rather than recording wrong statistics.
        on_failure=dandi_cache.SKIP,
        stages={"reading the NWB file": "file_read_errors.txt"},
        describe=lambda statistics: f"{statistics['n_internal_nodes']} internal nodes",
        checkpoint_every=50,
    )


if __name__ == "__main__":
    main()
