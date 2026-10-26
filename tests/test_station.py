import tempfile
import unittest
from pathlib import Path

from partdb_station.station import Station
from tests.fake_partdb import Fake
from tests.test_labels import LCSC


class StationFlow(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.tmp = Path(tempfile.mkdtemp())
        self.st = Station(self.tmp / "data", self.tmp / "cfg.json")
        self.st.set_config(self.fake.url, "tcp_test")

    def test_new_part_then_more_stock(self):
        self.assertEqual(self.st.status()["user"], "mike")
        r = self.st.scan(LCSC)
        self.assertEqual(r["matches"], [])
        sug = self.st.lookup(r["part"], r["vendor"])["suggest"]
        self.assertEqual((sug["category"], sug["spn"], sug["price"]), ("Op Amps", "C7593", "0.0812"))
        form = {"name": "LM358DR2G", "mpn": "LM358DR2G", "description": sug["description"], "category": sug["category"],
                "manufacturer": sug["manufacturer"], "footprint": sug["footprint"], "datasheet": sug["datasheet"], "image": sug["image"],
                "qty": 50, "location": "Drawer A1", "supplier": "LCSC", "spn": "C7593", "price": sug["price"], "currency": "USD"}
        res = self.st.save(form)
        self.assertFalse(res["warnings"], res)
        pid = res["part_id"]
        part = self.fake.db["parts"][pid]
        self.assertTrue(part["category"].startswith("/api/categories/"))
        self.assertEqual(len(self.fake.db["part_lots"]), 1)
        self.assertEqual(len(self.fake.db["orderdetails"]), 1)
        self.assertEqual(len(self.fake.db["attachments"]), 2)

        # the same label again finds the part (by MPN and LCSC number) and its lot in Drawer A1
        r2 = self.st.scan(LCSC)
        self.assertEqual([m["id"] for m in r2["matches"]], [pid])
        lot = r2["matches"][0]["lots"][0]
        self.assertEqual(lot["location"], "Drawer A1")
        res2 = self.st.save({"part_id": pid, "lot_id": lot["id"], "qty": 50, "supplier": "LCSC", "spn": "C7593"})
        self.assertEqual(self.fake.db["part_lots"][lot["id"]]["amount"], 100)
        self.assertEqual(len(self.fake.db["orderdetails"]), 1, "supplier number not added twice")
        self.assertEqual(len(self.st.recent()), 2)
        self.assertIn("added 50", res2["did"][0])

    def test_needs_category(self):
        with self.assertRaises(Exception):
            self.st.save({"name": "X"})

    def test_bad_token(self):
        self.st.set_config(token="nope")
        self.assertIn("token", self.st.status()["problem"])


if __name__ == "__main__":
    unittest.main()
