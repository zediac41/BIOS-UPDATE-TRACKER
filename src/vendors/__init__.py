from . import asus, msi, gigabyte, asrock

PARSERS = {
  "asus": asus.parse,
  "msi": msi.parse,
  "gigabyte": gigabyte.parse,
  "asrock": asrock.parse,
}
