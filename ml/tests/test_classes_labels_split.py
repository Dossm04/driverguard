"""Классы и синонимы, YOLO-разметка, сплит по сессиям без утечки."""

from pathlib import Path

from dgml.classes import CLASSES, EVENT_BY_CLASS, class_index, normalize
from dgml.labels import read_labels, remap, write_labels
from dgml.split import Item, leakage, session_of, split_by_session


def test_aliases_map_to_our_classes():
    assert normalize("Cell Phone") == "phone"
    assert normalize("cell-phone") == "phone"
    assert normalize("no_seatbelt") == "seatbelt_off"
    assert normalize("Seat belt") == "seatbelt_on"
    assert normalize("vape") == "cigarette"
    assert normalize("person") is None
    assert class_index("seatbelt_off") == 3 and len(CLASSES) == 4
    assert EVENT_BY_CLASS == {"phone": "phone", "cigarette": "smoking", "seatbelt_off": "seatbelt"}


def test_labels_roundtrip_and_remap(tmp_path: Path):
    p = tmp_path / "a.txt"
    write_labels(p, [(0, 0.5, 0.5, 0.2, 0.3), (7, 0.1, 0.1, 0.05, 0.05)])
    rows = read_labels(p)
    assert rows[0][0] == 0 and abs(rows[0][3] - 0.2) < 1e-6
    kept, dropped = remap(rows, {0: 1, 7: None})
    assert kept == [(1, 0.5, 0.5, 0.2, 0.3)] and dropped == 1
    assert read_labels(None) == [] and read_labels(tmp_path / "нет.txt") == []
    (tmp_path / "bad.txt").write_text("x y z\n3 0.5 0.5 0 0.1\n", encoding="utf-8")
    assert read_labels(tmp_path / "bad.txt") == []  # мусор и нулевая ширина отбрасываются


def test_session_from_filename_or_folder():
    assert session_of(Path("x/cabin__2026-09-10-ivanov__000012.jpg")) == ("cabin", "2026-09-10-ivanov")
    assert session_of(Path("raw/batch3/images/img42.jpg")) == ("batch3", "batch3")


def _items(sessions: dict[str, int]) -> list[Item]:
    out = []
    for s, n in sessions.items():
        for i in range(n):
            out.append(Item(image=Path(f"cabin__{s}__{i:06d}.jpg"), label=None, source="cabin", session=s))
    return out


def test_split_keeps_sessions_together_and_is_deterministic():
    items = _items({f"s{i:02d}": 10 + i for i in range(12)})
    a = split_by_session(items, seed=1)
    b = split_by_session(items, seed=1)
    assert [i.image for i in a["train"]] == [i.image for i in b["train"]]
    assert leakage(a) == []
    total = len(items)
    assert 0.55 * total <= len(a["train"]) <= 0.85 * total
    assert a["val"] and a["test"]
    sessions_train = {i.session for i in a["train"]}
    sessions_val = {i.session for i in a["val"]}
    assert not (sessions_train & sessions_val)


def test_split_single_session_goes_to_train_only():
    a = split_by_session(_items({"only": 30}))
    assert len(a["train"]) == 30 and not a["val"] and not a["test"]
    assert leakage(a) == []
