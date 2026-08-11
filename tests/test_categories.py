"""Resolving category paths against the vendored taxonomy.

The taxonomy is a DAG, not a tree: 231 categories sit at more than one place in
it, and a parent's results include everything beneath it. Both facts have to
survive into what the user sees, or a filter means something other than they
think it does.
"""

import pathlib

import pytest

from trends_research_cli import categories as module
from trends_research_cli.categories import (
    ALL_CATEGORIES,
    CategoryError,
    children_of,
    describe,
    load,
    paths_for,
    provenance,
    resolve,
    search,
)


def test_the_vendored_taxonomy_loads_and_is_the_expected_size():
    taxonomy = load()

    assert len(taxonomy) > 1000, "the taxonomy has ~1,133 unique ids"
    assert taxonomy[ALL_CATEGORIES] == "All categories"
    assert taxonomy[45] == "Health"


def test_it_records_where_it_came_from():
    """Vendored data without provenance is folklore."""
    source, fetched = provenance()

    assert "trends.google.com" in source
    assert fetched.count("-") == 2, "an ISO date"


# --- resolving by path -------------------------------------------------------


@pytest.mark.parametrize(
    "given",
    [
        "/Health/Health Conditions",
        "Health/Health Conditions",
        "Health Conditions",
        "health conditions",
        "  Health / Health Conditions  ",
    ],
)
def test_every_reasonable_spelling_of_a_path_resolves(given):
    """Names are globally unique, so a bare leaf is never ambiguous."""
    assert resolve(given) == 419


def test_a_leading_slash_is_accepted_but_not_required():
    assert resolve("/Health") == resolve("Health") == 45


def test_a_bare_slash_means_no_filter():
    """The root node is literally 'All categories', id 0."""
    assert resolve("/") == ALL_CATEGORIES == 0


def test_an_unknown_path_is_refused_with_a_suggestion():
    with pytest.raises(CategoryError, match="no category"):
        resolve("Health/Nonexistent Thing")


def test_the_error_suggests_near_matches():
    with pytest.raises(CategoryError) as caught:
        resolve("helth")

    assert "Health" in str(caught.value), "a typo should still point somewhere"


# --- the DAG ----------------------------------------------------------------


def test_a_category_reachable_by_two_paths_reports_both():
    """1104 'Animated Films' sits under both Comics & Animation and Movies."""
    paths = paths_for(1104)

    assert len(paths) == 2
    assert any(p.endswith("Comics & Animation/Animated Films") for p in paths)
    assert any(p.endswith("Movies/Animated Films") for p in paths)


def test_either_path_resolves_to_the_same_id():
    left = resolve("/Arts & Entertainment/Comics & Animation/Animated Films")
    right = resolve("/Arts & Entertainment/Movies/Animated Films")

    assert left == right == 1104


def test_paths_are_canonicalised_with_a_leading_slash():
    """Whatever the user typed, the output form is fully qualified."""
    assert describe(419).path == "/Health/Health Conditions"
    assert describe(45).path == "/Health"


# --- containment, which is the whole reason the tree is kept -----------------


def test_a_parent_reports_the_children_it_includes():
    """Verified live: filtering by a parent returns its descendants' traffic,
    so a caller has to be told what they just swept in."""
    described = describe(316)

    assert described.path == "/Arts & Entertainment/Comics & Animation"
    assert described.descendants >= 4
    assert "Anime & Manga" in described.child_names


def test_a_leaf_reports_no_descendants():
    """317 Anime & Manga has nothing beneath it, unlike 419 which has 31."""
    assert describe(317).descendants == 0
    assert describe(317).child_names == []


def test_a_mid_level_category_still_sweeps_in_everything_below_it():
    """`Health Conditions` looks specific and carries 31 sub-categories."""
    described = describe(419)

    assert described.descendants == 31
    assert "Cold & Flu" in described.child_names


def test_children_of_lists_the_immediate_level_only():
    names = {name for _, name in children_of(316)}

    assert names == {"Animated Films", "Anime & Manga", "Cartoons", "Comics"}


def test_an_ancestor_is_detectable_so_overlap_can_be_warned_about():
    """Comparing 45 against 419 compares a set with its own subset."""
    assert describe(419).is_within(45)
    assert not describe(45).is_within(419)
    assert not describe(419).is_within(3)


# --- search ------------------------------------------------------------------


def test_search_finds_by_substring_and_returns_paths():
    hits = dict(search("health"))

    assert 45 in hits and hits[45] == "/Health"
    assert any("Health Conditions" in p for p in hits.values())


def test_search_is_case_insensitive_and_finds_nothing_gracefully():
    assert search("HEALTH") == search("health")
    assert search("zzzznotathing") == []


def test_ids_that_do_not_exist_are_rejected():
    with pytest.raises(CategoryError, match="not in the taxonomy"):
        describe(88888)


def test_a_category_names_what_contains_it_nearest_first():
    """The other half of containment: a run filtered to /Health overlaps one
    filtered to its child, so both directions have to be visible."""
    described = describe(419)

    assert described.ancestor_paths == ("/Health",)


def test_the_root_is_not_named_as_a_container():
    """Everything is inside 'All categories'; saying so helps nobody."""
    assert all("All categories" not in p for p in describe(419).ancestor_paths)


def test_a_deep_category_lists_every_container_nearest_first():
    described = describe(1104)  # Animated Films

    assert described.ancestor_paths[0].count("/") >= 2, "deepest first"
    assert any("Arts & Entertainment" in p for p in described.ancestor_paths)


def test_a_top_level_category_has_no_containers():
    assert describe(45).ancestor_paths == ()


def test_there_is_no_network_path_in_this_module():
    """The taxonomy ships with the release and is never fetched at runtime.

    A refresh would mean a cache, a corrupt-cache fallback and their tests --
    a lot of machinery for a taxonomy that gained one category in seven years,
    when upgrading the package already covers it.
    """
    source = pathlib.Path(module.__file__).read_text()

    assert "urllib" not in source
    assert "http" not in source.replace("https://trends.google.com", "")
