import pytest

from lineage import yearwords


@pytest.mark.parametrize(
    "words, year",
    [
        ("1700 Zeeven entagtig", 1787),
        ("1700 zeven en tachtig", 1787),
        ("seventien hondert seven en tachtig", 1787),
        ("anno duysent seshondert twee en vijftich", 1652),
        ("achttienhonderd twee", 1802),
        ("millesimo septingentesimo octogesimo septimo", 1787),
        ("anno 1700 octogesimo", 1780),
        ("den 5 meert", None),
        ("", None),
    ],
)
def test_parse(words, year):
    assert yearwords.parse(words) == year
