"""Seams: sigfw.items.load_all (loaders), sigfw.dedupe.dedupe, sigfw.split (manifest, verify, leakage).

Fixtures are synthetic files with the real sources' schemas and filler text; no third-party data is used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_owndata import make_row

from sigfw.dedupe import dedupe
from sigfw.items import HELD_OUT, Item, LoaderError, canonicalize, load_all
from sigfw.split import build_manifest, find_leaks, verify_manifest

WORDS = [
    "amber",
    "basil",
    "cedar",
    "dune",
    "ember",
    "fjord",
    "glade",
    "harbor",
    "iris",
    "juniper",
    "kelp",
    "lagoon",
    "meadow",
    "nectar",
    "orchid",
    "pebble",
    "quartz",
    "ripple",
    "sable",
    "thistle",
    "umber",
    "velvet",
    "willow",
    "xenon",
    "yarrow",
    "zephyr",
    "anchor",
    "bridge",
    "candle",
    "drift",
    "easel",
    "feather",
    "garnet",
]


def filler(seed: int, words: int = 25) -> str:
    import random

    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(words))


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8", newline="\n")


def make_raw(tmp_path: Path, *, shadowing: bool = True) -> tuple[Path, Path]:
    raw = tmp_path / "raw"
    seed = iter(range(1000, 100000))
    mcptox = [
        {f"Srv_{i}_{j}": {"tool_content": filler(next(seed)), "paradigm": f"Template-{j}"} for j in (1, 2, 3)}
        for i in range(3)
    ]
    write_json(raw / "mcptox" / "pure_tool.json", mcptox)
    for kind in ("code", "text"):
        for split in ("train", "test"):
            cats = {f"{kind}-cat-{c}": [filler(next(seed)) for _ in range(2)] for c in range(3)}
            write_json(raw / "bipia" / f"{kind}_attack_{split}.json", cats)
    for variant in ("dh_base", "dh_enhanced", "ds_base", "ds_enhanced"):
        write_json(
            raw / "injecagent" / f"test_cases_{variant}.json",
            [{"Tool Response": filler(next(seed)), "Attack Type": "x"} for _ in range(4)],
        )
    own = tmp_path / "own" / "shadowing.jsonl"
    own.parent.mkdir(parents=True)
    if shadowing:
        own.write_text("".join(json.dumps(make_row(i)) + "\n" for i in range(35)), encoding="utf-8", newline="\n")
    return raw, own


# ---------------------------------------------------------------- loaders


def test_loaders_produce_the_expected_families_channels_and_unique_ids(tmp_path: Path) -> None:
    raw, own = make_raw(tmp_path)
    items = load_all(raw, own)
    fams = {i.family for i in items}
    assert fams == {
        "mcptox_t1", "mcptox_t2", "mcptox_t3", "bipia_code", "bipia_text", "shadowing",
        "injecagent_dh_base", "injecagent_dh_enhanced", "injecagent_ds_base", "injecagent_ds_enhanced",
    }  # fmt: skip
    assert len({i.id for i in items}) == len(items)
    assert all(i.label == "attack" for i in items)
    by_family = {f: {i.channel for i in items if i.family == f} for f in fams}
    assert by_family["mcptox_t3"] == {"tool_description"} and by_family["shadowing"] == {"tool_description"}
    assert by_family["bipia_code"] == {"tool_result"} and by_family["injecagent_dh_base"] == {"tool_result"}
    assert sum(i.family == "mcptox_t2" for i in items) == 3
    assert sum(i.family == "bipia_text" for i in items) == 2 * 3 * 2  # train+test, 3 categories, 2 each
    assert sum(i.family == "shadowing" for i in items) == 35
    assert {"mcptox_t3", "bipia_code", "bipia_text", "shadowing"} == HELD_OUT


def test_missing_raw_file_names_the_fetch_command(tmp_path: Path) -> None:
    raw, own = make_raw(tmp_path)
    (raw / "bipia" / "code_attack_test.json").unlink()
    with pytest.raises(LoaderError, match="sigfw data fetch"):
        load_all(raw, own)


def test_missing_shadowing_is_a_loader_error(tmp_path: Path) -> None:
    raw, own = make_raw(tmp_path, shadowing=False)
    with pytest.raises(LoaderError, match="shadowing"):
        load_all(raw, own)


def test_invalid_shadowing_set_is_refused(tmp_path: Path) -> None:
    raw, own = make_raw(tmp_path)
    own.write_text(own.read_text(encoding="utf-8").split("\n", 5)[5], encoding="utf-8")  # drops 5 rows: n=30
    with pytest.raises(LoaderError, match="check-own"):
        load_all(raw, own)


def test_unknown_mcptox_paradigm_is_refused(tmp_path: Path) -> None:
    raw, own = make_raw(tmp_path)
    write_json(raw / "mcptox" / "pure_tool.json", [{"X_1": {"tool_content": "t", "paradigm": "Template-9"}}])
    with pytest.raises(LoaderError, match="paradigm"):
        load_all(raw, own)


def test_canonicalize_normalises_text_and_keeps_everything_else() -> None:
    item = Item("i1", "src", "fam", "tool_result", "attack", "ig​nore")
    assert canonicalize([item]) == [Item("i1", "src", "fam", "tool_result", "attack", "ignore")]


# ---------------------------------------------------------------- dedupe


def mk(id_: str, family: str, text: str) -> Item:
    return Item(id_, "src", family, "tool_result", "attack", text)


def test_distinct_items_are_all_kept() -> None:
    items = [mk(f"a{i}", "dev_fam", filler(i)) for i in range(10)]
    kept, dropped = dedupe(items)
    assert [i.id for i in kept] == [i.id for i in items] and dropped == []


def test_exact_duplicate_is_dropped_and_the_first_wins() -> None:
    t = filler(1)
    kept, dropped = dedupe([mk("a", "f1", t), mk("b", "f1", t)])
    assert [i.id for i in kept] == ["a"]
    assert [(d.id, d.reason, d.of) for d in dropped] == [("b", "exact", "a")]


def test_near_duplicate_is_dropped() -> None:
    t = filler(2, words=60)
    kept, dropped = dedupe([mk("a", "f1", t), mk("b", "f1", t + " one more word")])
    assert [i.id for i in kept] == ["a"]
    assert dropped[0].reason == "near" and dropped[0].of == "a"


def test_heldout_wins_a_conflict_whatever_the_input_order() -> None:
    t = filler(3)
    kept, dropped = dedupe([mk("dev1", "dev_fam", t), mk("held1", "mcptox_t3", t)])
    assert [i.id for i in kept] == ["held1"]
    assert [(d.id, d.of) for d in dropped] == [("dev1", "held1")]


def test_dedupe_is_deterministic_and_independent_of_input_order() -> None:
    t = filler(4)
    items = [mk("b", "f1", t), mk("a", "f1", t), mk("c", "f1", filler(5))]
    k1, _ = dedupe(items)
    k2, _ = dedupe(list(reversed(items)))
    assert [i.id for i in k1] == [i.id for i in k2] == ["a", "c"]


# ---------------------------------------------------------------- manifest, verify, leakage


def build(tmp_path: Path, **kw: bool) -> tuple[list[Item], dict[str, object]]:
    raw, own = make_raw(tmp_path, **kw)
    kept, dropped = dedupe(canonicalize(load_all(raw, own)))
    return kept, build_manifest(kept, dropped)


def test_manifest_assigns_splits_counts_and_hashes_but_no_text(tmp_path: Path) -> None:
    kept, manifest = build(tmp_path)
    assert manifest["heldout_families"] == sorted(HELD_OUT)
    items = manifest["items"]
    assert isinstance(items, list) and len(items) == len(kept)
    assert {i["split"] for i in items if i["family"] in HELD_OUT} == {"frozen"}
    assert {i["split"] for i in items if i["family"] not in HELD_OUT} == {"dev"}
    assert all(len(i["sha256"]) == 64 for i in items)
    assert not any(k.text in json.dumps(manifest) for k in kept)
    assert manifest["normalizer_version"] == 1


def test_verify_passes_for_an_identical_rebuild_and_reports_heldout_four(tmp_path: Path) -> None:
    kept, manifest = build(tmp_path)
    ok, line = verify_manifest(manifest, kept)
    assert ok and line.startswith("MANIFEST_OK") and "heldout=4" in line


def test_verify_detects_a_changed_item(tmp_path: Path) -> None:
    kept, manifest = build(tmp_path)
    tampered = [
        Item(kept[0].id, kept[0].source, kept[0].family, kept[0].channel, "attack", kept[0].text + "!"),
        *kept[1:],
    ]
    ok, msg = verify_manifest(manifest, tampered)
    assert not ok and kept[0].id in msg


def test_verify_detects_a_missing_or_extra_item(tmp_path: Path) -> None:
    kept, manifest = build(tmp_path)
    assert not verify_manifest(manifest, kept[1:])[0]
    assert not verify_manifest(manifest, [*kept, mk("zzz", "mcptox_t1", "new text here")])[0]


def test_a_manifest_without_four_heldout_families_fails(tmp_path: Path) -> None:
    kept = [i for i in canonicalize(load_all(*make_raw(tmp_path))) if i.family != "shadowing"]
    kept, dropped = dedupe(kept)
    manifest = build_manifest(kept, dropped)
    ok, msg = verify_manifest(manifest, kept)
    assert not ok and "heldout=3" in msg


def test_find_leaks_flags_a_dev_item_near_a_frozen_item() -> None:
    t = filler(7, words=60)
    clean = [mk("d1", "dev_fam", filler(8)), mk("f1", "mcptox_t3", t)]
    assert find_leaks(clean, {"d1": "dev", "f1": "frozen"}) == []
    leaky = [*clean, mk("d2", "dev_fam", t + " tail")]
    leaks = find_leaks(leaky, {"d1": "dev", "f1": "frozen", "d2": "dev"})
    assert [(a, b) for a, b, _ in leaks] == [("d2", "f1")]
