"""Tile data structure tests."""
import pytest

from src.core.tiles import (
    Tile,
    create_tile,
    parse_tile,
    tile_index,
    index_to_tile,
    is_playable,
    PLAYABLE_TILES,
    GameState,
    Meld,
)


class TestCreateTile:
    def test_create_number_tile(self):
        t = create_tile("万", 3)
        assert t.suit == "万"
        assert t.value == 3
        assert t.is_flower is False

    def test_create_coerces_string_number_to_int(self):
        t = create_tile("万", "3")
        assert t.value == 3
        assert isinstance(t.value, int)

    def test_dong_feng_is_flower(self):
        assert create_tile("风", "东").is_flower is True

    def test_nan_feng_is_not_flower(self):
        assert create_tile("风", "南").is_flower is False
        assert create_tile("风", "西").is_flower is False
        assert create_tile("风", "北").is_flower is False

    def test_sanyuan_are_flowers(self):
        for v in ("中", "发", "白"):
            assert create_tile("三元", v).is_flower is True

    def test_season_are_flowers(self):
        for v in ("春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"):
            assert create_tile("季节", v).is_flower is True

    def test_number_tiles_not_flowers(self):
        for suit in ("万", "饼", "条"):
            for v in range(1, 10):
                assert create_tile(suit, v).is_flower is False


class TestParseTile:
    @pytest.mark.parametrize("s,suit,value", [
        ("3万", "万", 3), ("9条", "条", 9), ("1饼", "饼", 1), ("7万", "万", 7),
    ])
    def test_parse_number(self, s, suit, value):
        t = parse_tile(s)
        assert t.suit == suit
        assert t.value == value
        assert isinstance(t.value, int)

    @pytest.mark.parametrize("s,value,flower", [
        ("东风", "东", True), ("南风", "南", False),
        ("西风", "西", False), ("北风", "北", False),
    ])
    def test_parse_wind(self, s, value, flower):
        t = parse_tile(s)
        assert t.suit == "风"
        assert t.value == value
        assert t.is_flower is flower

    @pytest.mark.parametrize("s,wind", [
        ("东", "东"), ("南", "南"), ("西", "西"), ("北", "北"),
    ])
    def test_parse_bare_wind(self, s, wind):
        # single wind chars are accepted for CLI convenience
        t = parse_tile(s)
        assert t.suit == "风"
        assert t.value == wind
        assert t == parse_tile(wind + "风")

    def test_parse_sanyuan(self):
        for v in ("中", "发", "白"):
            t = parse_tile(v)
            assert t.suit == "三元"
            assert t.value == v
            assert t.is_flower is True

    def test_parse_season(self):
        t = parse_tile("春")
        assert t.suit == "季节"
        assert t.is_flower is True

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_tile("xx")
        with pytest.raises(ValueError):
            parse_tile("0万")


class TestEquality:
    def test_equal(self):
        assert create_tile("万", 3) == create_tile("万", 3)

    def test_not_equal_value(self):
        assert create_tile("万", 3) != create_tile("万", 4)

    def test_not_equal_suit(self):
        assert create_tile("万", 3) != create_tile("饼", 3)

    def test_hash_equal(self):
        assert hash(create_tile("万", 3)) == hash(create_tile("万", 3))

    def test_usable_in_set_and_dict(self):
        s = {create_tile("万", 3), create_tile("万", 3), create_tile("万", 4)}
        assert len(s) == 2
        d = {create_tile("万", 3): "x"}
        assert d[create_tile("万", 3)] == "x"


class TestStr:
    def test_number_str(self):
        assert str(create_tile("万", 3)) == "3万"

    def test_wind_str(self):
        assert str(create_tile("风", "南")) == "南风"
        assert str(create_tile("风", "东")) == "东风"

    def test_sanyuan_str(self):
        assert str(create_tile("三元", "中")) == "中"

    def test_season_str(self):
        assert str(create_tile("季节", "春")) == "春"


class TestPlayableIndex:
    def test_playable_count(self):
        assert len(PLAYABLE_TILES) == 30

    def test_playable_membership(self):
        assert is_playable(create_tile("万", 1)) is True
        assert is_playable(create_tile("风", "北")) is True
        assert is_playable(create_tile("风", "东")) is False   # flower
        assert is_playable(create_tile("三元", "中")) is False  # flower
        assert is_playable(create_tile("季节", "春")) is False  # flower

    @pytest.mark.parametrize("tile,idx", [
        (create_tile("万", 1), 0), (create_tile("万", 9), 8),
        (create_tile("饼", 1), 9), (create_tile("饼", 9), 17),
        (create_tile("条", 1), 18), (create_tile("条", 9), 26),
        (create_tile("风", "南"), 27), (create_tile("风", "西"), 28),
        (create_tile("风", "北"), 29),
    ])
    def test_tile_index(self, tile, idx):
        assert tile_index(tile) == idx

    def test_tile_index_flower_raises(self):
        with pytest.raises(ValueError):
            tile_index(create_tile("三元", "中"))

    def test_index_to_tile_roundtrip(self):
        for i in range(30):
            assert tile_index(index_to_tile(i)) == i


class TestGameState:
    def test_defaults(self):
        s = GameState()
        assert s.my_hand == []
        assert s.discards == {"left": [], "right": [], "opposite": []}
        assert s.melds == {"left": [], "right": [], "opposite": []}
        assert s.my_melds == []
        assert s.flowers_in_hand == []
        assert s.konged_flowers == []
        assert s.current_turn == "me"

    def test_independent_defaults(self):
        # mutable defaults must not be shared across instances
        a, b = GameState(), GameState()
        a.discards["left"].append(create_tile("万", 3))
        assert b.discards["left"] == []

    def test_meld(self):
        m = Meld(type="peng", tiles=[create_tile("万", 3)] * 3)
        assert m.type == "peng"
        assert len(m.tiles) == 3
