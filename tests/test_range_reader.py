import re
import httpx
import pytest
from backend.monitoring.range_reader import HTTPRangeReader


def test_range_reader_seek_cache_bounds_and_corrupt_disk_recovery(tmp_path):
    content=bytes(range(256))*5000;requests=[]
    def handle(request):
        start,end=map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',request.headers['range']).groups())
        requests.append((start,end))
        return httpx.Response(206,headers={'Content-Range':f'bytes {start}-{end}/{len(content)}','ETag':'test-fixture'},content=content[start:end+1])
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with HTTPRangeReader('https://example.invalid/explicit-fixture.tif',client=client,cache_dir=tmp_path) as reader:
            reader.seek(200000);assert reader.read(400000)==content[200000:600000]
            n=len(requests);reader.seek(200000);assert reader.read(20)==content[200000:200020]
            assert len(requests)==n
            with pytest.raises(OSError):reader.read()
            reader.seek(-10,2);assert reader.read(20)==content[-10:]
        assert all(end-start+1<=HTTPRangeReader.CHUNK for start,end in requests)
        for path in tmp_path.rglob('*.bin'):path.write_bytes(b'corrupt')
        with HTTPRangeReader('https://example.invalid/explicit-fixture.tif',client=client,cache_dir=tmp_path) as reader:
            reader.seek(200000);assert reader.read(400000)==content[200000:600000]


def test_range_reader_refuses_full_body_or_wrong_range():
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'not a range'))) as client:
        with pytest.raises(OSError):HTTPRangeReader('https://example.invalid/test.tif',client=client)
