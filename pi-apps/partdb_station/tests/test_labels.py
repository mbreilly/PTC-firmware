"""python -m unittest discover tests   (from ~/apps/partdb_station)"""
import io
import unittest

import zxingcpp
from PIL import Image

from partdb_station import labels
from partdb_station.decode import decode

DIGIKEY = ("[)>\x1e06\x1dPRMCF0805JT10K0CT-ND\x1d1PRMCF0805JT10K0\x1d30PRMCF0805JT10K0CT-ND\x1dK\x1d1K75345687"
           "\x1d10K90182345\x1d9D2312\x1d1TA5324\x1d11K1\x1d4LTW\x1dQ100\x1d11ZPICK\x1d12Z12345\x1d13Z123456\x1d20Z000000\x1e\x04")
MOUSER = "[)>\x1e06\x1dK12345\x1d14K001\x1d1PLM358DR\x1dQ25\x1d11K098765432\x1d4LMY\x1d1VTexas Instruments\x1e\x04"
LCSC = "{pbn:PICK2309120034,on:SO2309121234,pc:C7593,pm:LM358DR2G,qty:50,mc:,cc:1,pdi:93451234,hp:null,wc:JS}"


class Labels(unittest.TestCase):
    def test_digikey(self):
        r = labels.parse(DIGIKEY)
        p = r["part"]
        self.assertEqual((r["kind"], r["vendor"]), ("ecia", "digikey"))
        self.assertEqual((p["mpn"], p["spn"], p["qty"]), ("RMCF0805JT10K0", "RMCF0805JT10K0CT-ND", 100))
        self.assertEqual((p["order"], p["date_code"], p["lot"], p["country"]), ("75345687", "2312", "A5324", "TW"))

    def test_mouser(self):
        p = labels.parse(MOUSER)["part"]
        self.assertEqual((p["mpn"], p["qty"], p["po"], p["manufacturer"]), ("LM358DR", 25, "12345", "Texas Instruments"))
        self.assertEqual(labels.parse(MOUSER)["vendor"], "mouser")

    def test_scanner_standins(self):
        # what keyboard scanners and some decoders send in place of the invisible separators
        for gs, rs in (("<GS>", "<RS>"), ("{GS}", "{RS}"), ("␝", "␞"), ("^]", "^^")):
            s = MOUSER.replace("\x1d", gs).replace("\x1e", rs).replace("\x04", "")
            self.assertEqual(labels.parse(s)["part"]["mpn"], "LM358DR", gs)
        self.assertEqual(labels.parse("[)>06\x1d1PABC\x1dQ3")["part"]["qty"], 3)

    def test_lcsc(self):
        r = labels.parse(LCSC)
        self.assertEqual((r["vendor"], r["part"]["spn"], r["part"]["mpn"], r["part"]["qty"]), ("lcsc", "C7593", "LM358DR2G", 50))

    def test_tme(self):
        p = labels.parse("QTY:10 PN:LM358D-ST MFR:STM MPN:LM358DT PO:7744 https://www.tme.eu/details/LM358D-ST")["part"]
        self.assertEqual((p["spn"], p["mpn"], p["qty"], p["manufacturer"]), ("LM358D-ST", "LM358DT", 10, "STM"))

    def test_partdb_and_others(self):
        self.assertEqual(labels.parse("http://128.91.45.130/scan/part/12")["partdb"], {"type": "part", "id": 12})
        self.assertEqual(labels.parse("L0034")["partdb"], {"type": "lot", "id": 34})
        self.assertEqual(labels.parse("https://www.lcsc.com/product-detail/x_C7593.html")["part"]["spn"], "C7593")
        self.assertEqual(labels.parse("4006381333931")["part"]["gtin"], "4006381333931")
        self.assertEqual(labels.parse("  NE555P \n")["part"]["mpn"], "NE555P")


class Photos(unittest.TestCase):
    def test_datamatrix_photo(self):
        img = zxingcpp.create_barcode(DIGIKEY, zxingcpp.BarcodeFormat.DataMatrix).to_image(scale=6)
        canvas = Image.new("L", (1200, 900), 230)
        canvas.paste(Image.fromarray(__import__("numpy").asarray(img)), (500, 300))
        buf = io.BytesIO(); canvas.save(buf, "JPEG", quality=85)
        codes = decode(buf.getvalue())
        self.assertEqual(codes[0]["format"], "Data Matrix")
        self.assertEqual(labels.parse(codes[0]["text"])["part"]["spn"], "RMCF0805JT10K0CT-ND")


if __name__ == "__main__":
    unittest.main()
