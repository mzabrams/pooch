"""
Test the core class and factory function.
"""
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ..core import Pooch, download_action, stream_download
from ..utils import file_hash, get_logger, temporary_file
from ..downloaders import HTTPDownloader

from .utils import (
    pooch_test_url,
    pooch_test_registry,
    check_tiny_data,
    check_large_data,
    capture_log,
)

# FTP doesn't work on Travis CI so need to be able to skip tests there
ON_TRAVIS = bool(os.environ.get("TRAVIS", None))
DATA_DIR = str(Path(__file__).parent / "data")
REGISTRY = pooch_test_registry()
BASEURL = pooch_test_url()
REGISTRY_CORRUPTED = {
    # The same data file but I changed the hash manually to a wrong one
    "tiny-data.txt": "098h0894dba14b12085eacb204284b97e362f4f3e5a5807693cc90ef415c1b2d"
}


def test_pooch_local():
    "Setup a pooch that already has the local data and test the fetch."
    pup = Pooch(path=DATA_DIR, base_url="some bogus URL", registry=REGISTRY)
    true = os.path.join(DATA_DIR, "tiny-data.txt")
    fname = pup.fetch("tiny-data.txt")
    assert true == fname
    check_tiny_data(fname)


def test_pooch_custom_url():
    "Have pooch download the file from URL that is not base_url"
    with TemporaryDirectory() as local_store:
        path = Path(local_store)
        urls = {"tiny-data.txt": BASEURL + "tiny-data.txt"}
        # Setup a pooch in a temp dir
        pup = Pooch(path=path, base_url="", registry=REGISTRY, urls=urls)
        # Check that the logs say that the file is being downloaded
        with capture_log() as log_file:
            fname = pup.fetch("tiny-data.txt")
            logs = log_file.getvalue()
            assert logs.split()[0] == "Downloading"
            assert logs.split()[-1] == "'{}'.".format(path)
        check_tiny_data(fname)
        # Check that no logging happens when there are no events
        with capture_log() as log_file:
            fname = pup.fetch("tiny-data.txt")
            assert log_file.getvalue() == ""


def test_pooch_download():
    "Setup a pooch that has no local data and needs to download"
    with TemporaryDirectory() as local_store:
        path = Path(local_store)
        true_path = str(path / "tiny-data.txt")
        # Setup a pooch in a temp dir
        pup = Pooch(path=path, base_url=BASEURL, registry=REGISTRY)
        # Check that the logs say that the file is being downloaded
        with capture_log() as log_file:
            fname = pup.fetch("tiny-data.txt")
            logs = log_file.getvalue()
            assert logs.split()[0] == "Downloading"
            assert logs.split()[-1] == "'{}'.".format(path)
        # Check that the downloaded file has the right content
        assert true_path == fname
        check_tiny_data(fname)
        assert file_hash(fname) == REGISTRY["tiny-data.txt"]
        # Check that no logging happens when not downloading
        with capture_log() as log_file:
            fname = pup.fetch("tiny-data.txt")
            assert log_file.getvalue() == ""


def test_pooch_logging_level():
    "Setup a pooch and check that no logging happens when the level is raised"
    with TemporaryDirectory() as local_store:
        path = Path(local_store)
        urls = {"tiny-data.txt": BASEURL + "tiny-data.txt"}
        # Setup a pooch in a temp dir
        pup = Pooch(path=path, base_url="", registry=REGISTRY, urls=urls)
        # Capture only critical logging events
        with capture_log("CRITICAL") as log_file:
            fname = pup.fetch("tiny-data.txt")
            assert log_file.getvalue() == ""
        check_tiny_data(fname)


def test_pooch_update():
    "Setup a pooch that already has the local data but the file is outdated"
    with TemporaryDirectory() as local_store:
        path = Path(local_store)
        # Create a dummy version of tiny-data.txt that is different from the
        # one in the remote storage
        true_path = str(path / "tiny-data.txt")
        with open(true_path, "w") as fin:
            fin.write("different data")
        # Setup a pooch in a temp dir
        pup = Pooch(path=path, base_url=BASEURL, registry=REGISTRY)
        # Check that the logs say that the file is being updated
        with capture_log() as log_file:
            fname = pup.fetch("tiny-data.txt")
            logs = log_file.getvalue()
            assert logs.split()[0] == "Updating"
            assert logs.split()[-1] == "'{}'.".format(path)
        # Check that the updated file has the right content
        assert true_path == fname
        check_tiny_data(fname)
        assert file_hash(fname) == REGISTRY["tiny-data.txt"]
        # Check that no logging happens when not downloading
        with capture_log() as log_file:
            fname = pup.fetch("tiny-data.txt")
            assert log_file.getvalue() == ""


def test_pooch_corrupted():
    "Raise an exception if the file hash doesn't match the registry"
    # Test the case where the file wasn't in the directory
    with TemporaryDirectory() as local_store:
        path = os.path.abspath(local_store)
        pup = Pooch(path=path, base_url=BASEURL, registry=REGISTRY_CORRUPTED)
        with capture_log() as log_file:
            with pytest.raises(ValueError):
                pup.fetch("tiny-data.txt")
            logs = log_file.getvalue()
            assert logs.split()[0] == "Downloading"
            assert logs.split()[-1] == "'{}'.".format(path)
    # and the case where the file exists but hash doesn't match
    pup = Pooch(path=DATA_DIR, base_url=BASEURL, registry=REGISTRY_CORRUPTED)
    with capture_log() as log_file:
        with pytest.raises(ValueError):
            pup.fetch("tiny-data.txt")
        logs = log_file.getvalue()
        assert logs.split()[0] == "Updating"
        assert logs.split()[-1] == "'{}'.".format(DATA_DIR)


def test_pooch_file_not_in_registry():
    "Should raise an exception if the file is not in the registry."
    pup = Pooch(
        path="it shouldn't matter", base_url="this shouldn't either", registry=REGISTRY
    )
    with pytest.raises(ValueError):
        pup.fetch("this-file-does-not-exit.csv")


def test_pooch_load_registry():
    "Loading the registry from a file should work"
    pup = Pooch(path="", base_url="")
    pup.load_registry(os.path.join(DATA_DIR, "registry.txt"))
    assert pup.registry == REGISTRY
    assert pup.registry_files.sort() == list(REGISTRY).sort()


def test_pooch_load_registry_fileobj():
    "Loading the registry from a file object"
    path = os.path.join(DATA_DIR, "registry.txt")

    # Binary mode
    pup = Pooch(path="", base_url="")
    with open(path, "rb") as fin:
        pup.load_registry(fin)
    assert pup.registry == REGISTRY
    assert pup.registry_files.sort() == list(REGISTRY).sort()

    # Text mode
    pup = Pooch(path="", base_url="")
    with open(path, "r") as fin:
        pup.load_registry(fin)
    assert pup.registry == REGISTRY
    assert pup.registry_files.sort() == list(REGISTRY).sort()


def test_pooch_load_registry_custom_url():
    "Load the registry from a file with a custom URL inserted"
    pup = Pooch(path="", base_url="")
    pup.load_registry(os.path.join(DATA_DIR, "registry-custom-url.txt"))
    assert pup.registry == REGISTRY
    assert pup.urls == {"tiny-data.txt": "https://some-site/tiny-data.txt"}


def test_pooch_load_registry_invalid_line():
    "Should raise an exception when a line doesn't have two elements"
    pup = Pooch(path="", base_url="", registry={})
    with pytest.raises(IOError):
        pup.load_registry(os.path.join(DATA_DIR, "registry-invalid.txt"))


def test_check_availability():
    "Should correctly check availability of existing and non existing files"
    # Check available remote file
    pup = Pooch(path=DATA_DIR, base_url=BASEURL, registry=REGISTRY)
    assert pup.is_available("tiny-data.txt")
    # Check non available remote file
    pup = Pooch(path=DATA_DIR, base_url=BASEURL + "wrong-url/", registry=REGISTRY)
    assert not pup.is_available("tiny-data.txt")
    # Wrong file name
    registry = {"not-a-real-data-file.txt": "notarealhash"}
    registry.update(REGISTRY)
    pup = Pooch(path=DATA_DIR, base_url=BASEURL, registry=registry)
    assert not pup.is_available("not-a-real-data-file.txt")


# https://blog.travis-ci.com/2018-07-23-the-tale-of-ftp-at-travis-ci
@pytest.mark.skipif(ON_TRAVIS, reason="FTP is not allowed on Travis CI")
def test_check_availability_on_ftp():
    "Should correctly check availability of existing and non existing files"
    # Check available remote file on FTP server
    pup = Pooch(
        path=DATA_DIR,
        base_url="ftp://speedtest.tele2.net/",
        registry={
            "100KB.zip": "f627ca4c2c322f15db26152df306bd4f983f0146409b81a4341b9b340c365a16",
            "doesnot_exist.zip": "jdjdjdjdflld",
        },
    )
    assert pup.is_available("100KB.zip")
    # Check non available remote file
    assert not pup.is_available("doesnot_exist.zip")


def test_fetch_with_downloader(capsys):
    "Setup a downloader function for fetch"

    def download(url, output_file, pup):  # pylint: disable=unused-argument
        "Download through HTTP and warn that we're doing it"
        get_logger().info("downloader executed")
        HTTPDownloader()(url, output_file, pup)

    with TemporaryDirectory() as local_store:
        path = Path(local_store)
        # Setup a pooch in a temp dir
        pup = Pooch(path=path, base_url=BASEURL, registry=REGISTRY)
        # Check that the logs say that the file is being downloaded
        with capture_log() as log_file:
            fname = pup.fetch("large-data.txt", downloader=download)
            logs = log_file.getvalue()
            lines = logs.splitlines()
            assert len(lines) == 2
            assert lines[0].split()[0] == "Downloading"
            assert lines[1] == "downloader executed"
        # Read stderr and make sure no progress bar was printed by default
        assert not capsys.readouterr().err
        # Check that the downloaded file has the right content
        check_large_data(fname)
        # Check that no logging happens when not downloading
        with capture_log() as log_file:
            fname = pup.fetch("large-data.txt")
            assert log_file.getvalue() == ""


def test_invalid_hash_alg():
    "Test an invalid hashing algorithm"
    pup = Pooch(
        path=DATA_DIR, base_url=BASEURL, registry={"tiny-data.txt": "blah:1234"}
    )
    with pytest.raises(ValueError) as exc:
        pup.fetch("tiny-data.txt")

    assert "'blah'" in str(exc.value)


def test_alternative_hashing_algorithms():
    "Test different hashing algorithms using local data"
    fname = os.path.join(DATA_DIR, "tiny-data.txt")
    check_tiny_data(fname)
    with open(fname, "rb") as fin:
        data = fin.read()
    for alg in ("sha512", "md5"):
        hasher = hashlib.new(alg)
        hasher.update(data)
        registry = {"tiny-data.txt": "{}:{}".format(alg, hasher.hexdigest())}
        pup = Pooch(path=DATA_DIR, base_url="some bogus URL", registry=registry)
        assert fname == pup.fetch("tiny-data.txt")
        check_tiny_data(fname)


def test_download_action():
    "Test that the right action is performed based on file existing"
    action, verb = download_action(
        Path("this_file_does_not_exist.txt"), known_hash=None
    )
    assert action == "download"
    assert verb == "Downloading"

    with temporary_file() as tmp:
        action, verb = download_action(Path(tmp), known_hash="not the correct hash")
    assert action == "update"
    assert verb == "Updating"

    with temporary_file() as tmp:
        with open(tmp, "w") as output:
            output.write("some data")
        action, verb = download_action(Path(tmp), known_hash=file_hash(tmp))
    assert action == "fetch"
    assert verb == "Fetching"


@pytest.mark.parametrize("fname", ["tiny-data.txt", "subdir/tiny-data.txt"])
def test_stream_download(fname):
    "Check that downloading a file over HTTP works as expected"
    # Use the data in store/ because the subdir is in there for some reason
    url = BASEURL + "store/" + fname
    known_hash = REGISTRY[fname]
    downloader = HTTPDownloader()
    with TemporaryDirectory() as local_store:
        destination = Path(local_store) / fname
        assert not destination.exists()
        stream_download(url, destination, known_hash, downloader, pooch=None)
        assert destination.exists()
        check_tiny_data(str(destination))
