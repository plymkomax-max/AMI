"""Тесты Data Engine: нормализация, парсинг CSV."""
from app.models.listing import ListingCondition
from app.services.importer import detect_delimiter, parse_csv_content
from app.services.listing_service import (
    make_listing_id,
    normalize_condition,
    normalize_condition_from_llm,
    normalize_price,
    parse_datetime,
)


class TestNormalizePrice:
    def test_int(self):
        assert normalize_price(12500) == 12500.0

    def test_float(self):
        assert normalize_price(12500.5) == 12500.5

    def test_string_spaces(self):
        assert normalize_price("12 500 ₽") == 12500.0

    def test_string_rub(self):
        assert normalize_price("12 500 руб") == 12500.0

    def test_comma_thousands(self):
        assert normalize_price("12,500") == 12500.0

    def test_decimal_comma(self):
        assert normalize_price("12500,50") == 12500.5

    def test_mixed(self):
        assert normalize_price("12,500.50") == 12500.5

    def test_european(self):
        assert normalize_price("1.234,56") == 1234.56

    def test_invalid(self):
        assert normalize_price("бесплатно") is None

    def test_empty(self):
        assert normalize_price("") is None

    def test_none(self):
        assert normalize_price(None) is None

    def test_negative(self):
        assert normalize_price("-100") is None


class TestNormalizeCondition:
    def test_new(self):
        assert normalize_condition("Новый") == ListingCondition.NEW

    def test_broken(self):
        assert normalize_condition("неисправен") == ListingCondition.BROKEN

    def test_for_parts(self):
        assert normalize_condition("на запчасти") == ListingCondition.FOR_PARTS

    def test_good(self):
        assert normalize_condition("good") == ListingCondition.GOOD

    def test_llm_broken(self):
        assert normalize_condition_from_llm("не включается, разбит экран") == ListingCondition.BROKEN

    def test_llm_new(self):
        assert normalize_condition_from_llm("новый запечатанный") == ListingCondition.NEW

    def test_llm_unknown(self):
        assert normalize_condition_from_llm("обычное состояние") == ListingCondition.GOOD


class TestListingID:
    def test_stable(self):
        assert make_listing_id("avito", "123") == make_listing_id("avito", "123")

    def test_different(self):
        assert make_listing_id("avito", "123") != make_listing_id("avito", "124")

    def test_source_normalized(self):
        assert make_listing_id("Avito ", "1") == make_listing_id("avito", "1")


class TestDates:
    def test_iso(self):
        assert parse_datetime("2026-01-15") is not None

    def test_russian(self):
        parsed = parse_datetime("15.01.2026")
        assert parsed is not None
        assert parsed.year == 2026 and parsed.month == 1 and parsed.day == 15

    def test_with_time(self):
        assert parse_datetime("15.01.2026 14:30") is not None

    def test_invalid_returns_none(self):
        assert parse_datetime("вчера") is None


class TestCSVImport:
    def test_parse_basic(self):
        content = """external_id,title,price,condition,city
        avito1,iPhone 13,45 000 ₽,хорошее,Москва
        avito2,MacBook Pro,120 000 руб,новый,СПб
        """
        records = parse_csv_content(content)
        assert len(records) == 2
        assert records[0]["external_id"] == "avito1"
        assert records[0]["price"] == 45000.0
        assert records[0]["city"] == "Москва"

    def test_parse_missing_external_id(self):
        content = """title,price
        iPhone 14,60000
        """
        records = parse_csv_content(content)
        assert len(records) == 1
        assert records[0]["external_id"].startswith("gen_")

    def test_generated_id_is_stable_across_prices(self):
        first = parse_csv_content("title,price\nXiaomi 12,20000\n")[0]["external_id"]
        second = parse_csv_content("title,price\nXiaomi 12,18000\n")[0]["external_id"]
        assert first == second

    def test_semicolon_delimiter(self):
        content = "external_id;title;price\nx1;iPhone;100\nx2;iPad;200\n"
        records = parse_csv_content(content)
        assert len(records) == 2
        assert records[1]["price"] == 200.0

    def test_cp1251(self):
        content = "external_id,title,price\nc1,Телефон,1000\n".encode("cp1251")
        records = parse_csv_content(content)
        assert records[0]["title"] == "Телефон"

    def test_bom_and_russian_headers(self):
        content = "\ufeffНазвание;Цена;Город\niPhone 13;45 000;Москва\n"
        records = parse_csv_content(content.encode("utf-8"))
        assert records[0]["title"] == "iPhone 13"
        assert records[0]["price"] == 45000.0
        assert records[0]["city"] == "Москва"

    def test_date_parsed_to_datetime(self):
        records = parse_csv_content("external_id,title,price,published_at\nd1,x,1,15.01.2026\n")
        assert records[0]["published_at"].year == 2026

    def test_defects(self):
        content = """external_id,title,price,defects
        avito3,PS5,30000,"разбит, трещина"
        """
        records = parse_csv_content(content)
        assert "разбит" in records[0]["defects"]

    def test_duplicate_rows_in_one_file_collapse(self):
        content = "external_id,title,price\nx1,Товар,100\nx1,Товар,90\n"
        records = parse_csv_content(content)
        assert len(records) == 1
        assert records[0]["price"] == 90.0

    def test_detect_delimiter(self):
        assert detect_delimiter("a;b;c\n1;2;3\n") == ";"
        assert detect_delimiter("a,b,c\n1,2,3\n") == ","
