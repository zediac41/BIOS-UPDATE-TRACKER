import json, yaml, time
from pathlib import Path
from vendors import asus, msi, gigabyte, asrock

VENDOR_FUNCS = {
    "ASUS": asus.get_last_two_versions,
    "MSI": msi.get_last_two_versions,
    "GIGABYTE": gigabyte.get_last_two_versions,
    "ASRock": asrock.get_last_two_versions,
}

def main():
    boards_file = Path(__file__).resolve().parents[1] / "boards.yaml"
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    out_json = docs_dir / "data.json"

    boards = yaml.safe_load(boards_file.read_text(encoding="utf-8")).get("boards", [])
    results = []

    for b in boards:
        name = b.get("name")
        vendor = b.get("vendor")
        url = b.get("support_url")
        func = VENDOR_FUNCS.get(vendor)
        print(f"Fetching {vendor} | {name} ...")
        two = []
        error = None
        if func:
            try:
                two = func(url)
            except Exception as e:
                error = str(e)
        else:
            error = "Unknown vendor"

        item = {
            "board": name,
            "vendor": vendor,
            "latest": two[0] if len(two) > 0 else None,
            "previous": two[1] if len(two) > 1 else None,
            "download_page": url,
        }
        if error:
            item["error"] = error
        results.append(item)
        time.sleep(0.8)  # be gentle

    out_json.write_text(json.dumps({"generated_at": time.time(), "items": results}, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")

if __name__ == "__main__":
    main()
