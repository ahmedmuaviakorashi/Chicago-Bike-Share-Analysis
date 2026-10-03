import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE_URL = "https://divvy-tripdata.s3.amazonaws.com"


def monthly_url(year: int, month: int) -> str:
    return f"{BASE_URL}/{year}{month:02d}-divvy-tripdata.zip"


def download_month(year: int, month: int, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{year}{month:02d}-divvy-tripdata.csv"
    if target.exists() and target.stat().st_size > 0:
        return target

    request = urllib.request.Request(
        monthly_url(year, month),
        headers={"User-Agent": "Chicago-Bike-Share-Analysis/1.0"},
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        archive = Path(temporary_directory) / "trips.zip"
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            archive.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)

        with zipfile.ZipFile(archive) as bundle:
            csv_members = [
                item
                for item in bundle.infolist()
                if item.filename.lower().endswith(".csv")
                and "__macosx" not in item.filename.lower()
                and not Path(item.filename).name.startswith("._")
            ]
            if len(csv_members) != 1:
                raise RuntimeError(
                    f"Expected one CSV in {archive.name}; found {len(csv_members)}."
                )
            temporary_target = target.with_suffix(".csv.part")
            with bundle.open(csv_members[0]) as source, temporary_target.open("wb") as output:
                shutil.copyfileobj(source, output)
            temporary_target.replace(target)
    return target


def download_year(year: int, destination: Path) -> list[Path]:
    if year < 2020:
        raise ValueError("The monthly Divvy schema used here begins in 2020.")
    return [download_month(year, month, destination) for month in range(1, 13)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download official monthly Divvy trip files.")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--destination", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    for path in download_year(args.year, args.destination):
        print(path)


if __name__ == "__main__":
    main()
