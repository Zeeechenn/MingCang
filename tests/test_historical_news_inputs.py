from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/evidence"))

import historical_news_inputs as extract_news


class ExtractNewsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="news input space ")
        self.root = Path(self.temp.name)
        self.db = self.root / "source snapshot with spaces.sqlite"
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE news (
              id INTEGER PRIMARY KEY, symbol TEXT, title TEXT, url TEXT,
              published_at TEXT, source TEXT, summary TEXT, sentiment_score REAL,
              fetched_at TEXT, content TEXT, provider TEXT, asset_key TEXT, market TEXT
            );
            CREATE TABLE announcements (
              id INTEGER PRIMARY KEY, symbol TEXT, title TEXT, content TEXT,
              ann_type TEXT, published_at TEXT, source_url TEXT, provider TEXT,
              fetched_at TEXT, asset_key TEXT, market TEXT, currency TEXT
            );
            INSERT INTO news VALUES
              (1,'000001','eligible','https://cn/1','2026-08-18 15:00:00','wire',
               'do-not-export-summary',0.9,'2026-08-18 18:00:00','body','wire',NULL,'CN'),
              (2,'00700','foreign','https://hk/2','2026-08-18 15:00:00','wire',
               NULL,NULL,'2026-08-18 18:00:00','body','wire',NULL,'HK'),
              (3,'000002','bad-clock','https://cn/3','2026-08-18 15:00:00','wire',
               NULL,NULL,'2026-08-18 14:00:00','body','wire',NULL,'CN'),
              (4,'000003','cutoff-fetch','https://cn/4','2026-08-18 15:00:00','wire',
               NULL,NULL,'2026-08-19 00:00:00','body','wire',NULL,'CN'),
              (5,'000004','cutoff-pub','https://cn/5','2026-08-19 00:00:00','wire',
               NULL,NULL,'2026-08-19 00:00:00','body','wire',NULL,'CN'),
              (6,'SH600000','prefixed-symbol','https://cn/6','2026-08-18 15:00:00','wire',
               NULL,NULL,'2026-08-18 16:00:00','body','wire',NULL,'CN');
            INSERT INTO announcements VALUES
              (1,'688001','eligible notice','notice body','notice',
               '2026-08-18 09:00:00','https://cn/notice','official',
               '2026-08-18 10:00:00',NULL,'CN','CNY');
        """)
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_cn_cutoff_fields_and_hashes_with_uri_encoded_path(self) -> None:
        out = self.root / "output"
        manifest = extract_news.extract(self.db, out, [date(2026, 8, 19)], 3)
        self.assertIn("%20", extract_news.sqlite_uri(self.db))
        self.assertEqual(
            manifest["snapshot"]["sha256_before"], manifest["snapshot"]["sha256_after"]
        )
        self.assertEqual(manifest["records"]["unique_database_rows_exported"], 2)
        self.assertEqual(
            manifest["trial_window"]["by_decision_date"]["2026-08-19"]["symbol_day_count"], 2
        )
        self.assertEqual(
            manifest["records"]["audit_counts"]["news_excluded_non_cn_or_unknown_market"], 1
        )
        self.assertEqual(
            manifest["records"]["audit_counts"]["news_fetched_before_published_rejected"], 1
        )
        self.assertEqual(manifest["records"]["audit_counts"]["news_excluded_invalid_cn_symbol"], 1)
        rows = [json.loads(line) for line in (out / "raw_inputs.jsonl").read_text().splitlines()]
        self.assertEqual({row["raw_fields"]["symbol"] for row in rows}, {"000001", "688001"})
        news = next(row for row in rows if row["source_table"] == "news")
        self.assertNotIn("summary", news["raw_fields"])
        self.assertNotIn("sentiment_score", news["raw_fields"])
        self.assertEqual(len(news["raw_fields_sha256"]), 64)
        self.assertEqual(len(news["record_sha256"]), 64)

    def test_rejects_duplicates_and_invalid_lookback(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate decision dates"):
            extract_news.parse_dates(["2026-08-19", "2026-08-19"])
        with self.assertRaisesRegex(ValueError, "lookback calendar days"):
            extract_news.extract(self.db, self.root / "unused", [date(2026, 8, 19)], -1)

    def test_rejects_symlink_and_any_sqlite_sidecar(self) -> None:
        link = self.root / "linked.sqlite"
        link.symlink_to(self.db)
        with self.assertRaisesRegex(ValueError, "symlink"):
            extract_news.validate_snapshot_path(link)
        sidecar = Path(str(self.db) + "-shm")
        sidecar.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "sidecar"):
            extract_news.validate_snapshot_path(self.db)


if __name__ == "__main__":
    unittest.main()
