import argparse
from pathlib import Path

from bikeshare_analysis.download import download_year
from bikeshare_analysis.pipeline import run_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and analyze Divvy trip data.")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        download_year(args.year, args.raw_dir)
    run_analysis(args.raw_dir, args.output_dir, args.year)


if __name__ == "__main__":
    main()
