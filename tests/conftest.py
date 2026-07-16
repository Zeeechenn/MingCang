"""pytest 配置：用 in-memory SQLite，每个 test session 独立 schema"""
import os
import sys

import pytest

# 确保 PYTHONPATH 包含项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def test_db():
    """每个测试用全新的内存 SQLite + 全部表"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.data.database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture(autouse=True)
def isolate_persistent_job_ledger(monkeypatch):
    """Unit tests must not write scheduler metadata into the developer's live DB."""
    from backend.config import settings

    monkeypatch.setattr(settings, "job_ledger_enabled", False)


@pytest.fixture
def sample_stocks(test_db):
    """3 只测试股，含行业"""
    from backend.data.database import Stock
    stocks = [
        Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True),
        Stock(symbol="300308", name="中际旭创", market="CN", industry="电子", active=True),
        Stock(symbol="603986", name="兆易创新", market="CN", industry="电子", active=True),
    ]
    for s in stocks:
        test_db.add(s)
    test_db.commit()
    return stocks
