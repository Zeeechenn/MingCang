from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_runtime_schema_backfills_legacy_market_identity():
    from backend.data.schema_runtime import _ensure_market_identity_schema

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE stocks(symbol TEXT PRIMARY KEY, name TEXT, market TEXT, active BOOLEAN)"))
        conn.execute(text("CREATE TABLE prices(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, close REAL)"))
        conn.execute(text("INSERT INTO stocks VALUES ('600519','贵州茅台','CN',1)"))
        conn.execute(text("INSERT INTO prices VALUES (1,'600519','2026-07-14',1500)"))

    with engine.begin() as conn:
        _ensure_market_identity_schema(conn)

    with engine.connect() as conn:
        stock = conn.execute(text(
            "SELECT asset_key,currency,timezone,exchange,lot_size FROM stocks"
        )).one()
        price = conn.execute(text(
            "SELECT asset_key,market,currency FROM prices"
        )).one()
    assert tuple(stock) == ("CN:600519", "CNY", "Asia/Shanghai", "SSE/SZSE/BSE", 100)
    assert tuple(price) == ("CN:600519", "CN", "CNY")


def test_orm_models_fill_hk_us_identity_before_insert():
    from backend.data.models.market import Price, Stock
    from backend.data.orm import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        hk = Stock(symbol="700", name="腾讯控股", market="HK", active=True, lot_size=100)
        us_price = Price(
            symbol="aapl.o",
            market="US",
            date="2026-07-14",
            open=200,
            high=202,
            low=198,
            close=201,
            volume=1_000,
        )
        db.add_all([hk, us_price])
        db.commit()
        assert hk.symbol == "00700"
        assert hk.asset_key == "HK:00700"
        assert hk.currency == "HKD"
        assert hk.timezone == "Asia/Hong_Kong"
        assert us_price.symbol == "AAPL"
        assert us_price.asset_key == "US:AAPL"
        assert us_price.currency == "USD"


def test_legacy_hk_symbol_resolves_to_normalized_stock():
    from backend.data.instruments import resolve_stock
    from backend.data.models.market import Stock
    from backend.data.orm import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Stock(symbol="700", name="腾讯控股", market="HK", active=True))
        db.commit()
        assert resolve_stock(db, "700").asset_key == "HK:00700"
        assert resolve_stock(db, "0700.HK", market="HK").symbol == "00700"


def test_same_raw_symbol_and_date_can_coexist_across_markets():
    from backend.data.models.market import Price, Stock
    from backend.data.orm import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            Stock(symbol="DUAL", name="CN listing", market="CN", active=True),
            Stock(symbol="DUAL", name="US listing", market="US", active=True),
            Price(symbol="DUAL", market="CN", date="2026-07-14", open=1, high=1, low=1, close=1, volume=1),
            Price(symbol="DUAL", market="US", date="2026-07-14", open=2, high=2, low=2, close=2, volume=1),
        ])
        db.commit()
        assert db.query(Stock).filter(Stock.symbol == "DUAL").count() == 2
        assert db.query(Price).filter(Price.symbol == "DUAL").count() == 2


def test_runtime_migration_replaces_symbol_only_primary_and_unique_keys():
    from backend.data.schema_runtime import _ensure_market_identity_schema

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE stocks(symbol TEXT PRIMARY KEY, name TEXT, market TEXT, active BOOLEAN)"))
        conn.execute(text(
            "CREATE TABLE prices(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, date TEXT, close REAL, "
            "UNIQUE(symbol, date))"
        ))
        conn.execute(text("INSERT INTO stocks VALUES ('DUAL','CN listing','CN',1)"))
        conn.execute(text("INSERT INTO prices(symbol,date,close) VALUES ('DUAL','2026-07-14',1)"))
        _ensure_market_identity_schema(conn)
        conn.execute(text(
            "INSERT INTO stocks(asset_key,symbol,name,market,active) "
            "VALUES ('US:DUAL','DUAL','US listing','US',1)"
        ))
        conn.execute(text(
            "INSERT INTO prices(asset_key,market,symbol,date,close) "
            "VALUES ('US:DUAL','US','DUAL','2026-07-14',2)"
        ))

    with engine.connect() as conn:
        stock_pk = [row[1] for row in conn.execute(text("PRAGMA table_info(stocks)")) if row[5]]
        assert stock_pk == ["asset_key"]
        assert conn.execute(text("SELECT count(*) FROM stocks WHERE symbol='DUAL'")).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM prices WHERE symbol='DUAL'")).scalar() == 2
