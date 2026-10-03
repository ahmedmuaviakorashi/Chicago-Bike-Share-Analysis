import io
import zipfile
from pathlib import Path

from bikeshare_analysis import download
from bikeshare_analysis.download import monthly_url


def test_monthly_url() -> None:
    assert monthly_url(2024, 1) == (
        "https://divvy-tripdata.s3.amazonaws.com/202401-divvy-tripdata.zip"
    )


def test_download_ignores_macos_metadata(tmp_path: Path, monkeypatch) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("202401-divvy-tripdata.csv", "ride_id\nr1\n")
        bundle.writestr("__MACOSX/._202401-divvy-tripdata.csv", "metadata")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(
        download.urllib.request,
        "urlopen",
        lambda request, timeout: Response(archive.getvalue()),
    )
    result = download.download_month(2024, 1, tmp_path)
    assert result.read_text(encoding="utf-8") == "ride_id\nr1\n"
