"""Exact, bounded public COG range reads for unreliable large GDAL transfers."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import io
import re
import threading
import time
import httpx


class HTTPRangeReader(io.RawIOBase):
    CHUNK=262144
    def __init__(self,url,client=None,cache_dir=None):
        super().__init__()
        self.name=url;self.position=0;self.cache=OrderedDict();self.lock=threading.Lock()
        self.client=client or httpx.Client(timeout=12,follow_redirects=False,limits=httpx.Limits(max_connections=4,max_keepalive_connections=4))
        self.owns_client=client is None
        with self.client.stream('GET',url,headers={'Range':'bytes=0-0','User-Agent':'EcoLogicDev/4.1'}) as response:
            response.raise_for_status()
            match=re.fullmatch(r'bytes 0-0/(\d+)',response.headers.get('content-range',''))
            if response.status_code!=206 or not match:raise OSError('Source does not support exact HTTP ranges')
            self.size=int(match[1])
            if len(response.read())!=1:raise OSError('Source range length differs')
            identity=url+response.headers.get('etag','')+str(self.size)
        self.disk=Path(cache_dir)/hashlib.sha256(identity.encode()).hexdigest()[:24] if cache_dir else None
        if self.disk:self.disk.mkdir(parents=True,exist_ok=True)
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        target=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if target<0:raise OSError('Invalid source seek')
        self.position=target;return target
    def _chunk(self,start):
        with self.lock:
            if start in self.cache:
                self.cache.move_to_end(start);return self.cache[start]
        end=min(self.size,start+self.CHUNK)-1
        disk=self.disk/f'{start}.bin' if self.disk else None
        if disk and disk.exists():
            saved=disk.read_bytes();data=saved[:-32]
            if len(data)==end-start+1 and hashlib.sha256(data).digest()==saved[-32:]:return data
        for attempt in range(3):
            try:
                with self.client.stream('GET',self.name,headers={'Range':f'bytes={start}-{end}','User-Agent':'EcoLogicDev/4.1'}) as response:
                    response.raise_for_status()
                    expected=f'bytes {start}-{end}/{self.size}'
                    if response.status_code!=206 or response.headers.get('content-range')!=expected:raise OSError('Source returned a different byte range')
                    data=bytearray()
                    for part in response.iter_bytes():
                        data.extend(part)
                        if len(data)>end-start+1:raise OSError('Source range exceeds requested bound')
                    if len(data)!=end-start+1:raise OSError('Source returned a truncated byte range')
                data=bytes(data)
                if disk:
                    temporary=disk.with_suffix('.partial')
                    temporary.write_bytes(data+hashlib.sha256(data).digest());temporary.replace(disk)
                with self.lock:
                    self.cache[start]=data
                    if len(self.cache)>16:self.cache.popitem(last=False)
                return data
            except (OSError,httpx.HTTPError):
                if attempt==2:raise
                time.sleep(.3*(attempt+1))
    def read(self,size=-1):
        if size<0 or size>8_388_608:raise OSError('Whole-scene reads are disabled')
        stop=min(self.size,self.position+size);parts=[]
        starts=list(range(self.position//self.CHUNK*self.CHUNK,stop,self.CHUNK))
        if len(starts)>1:
            with ThreadPoolExecutor(max_workers=4) as pool:chunks=dict(zip(starts,pool.map(self._chunk,starts)))
        else:chunks={start:self._chunk(start) for start in starts}
        while self.position<stop:
            base=self.position//self.CHUNK*self.CHUNK
            chunk=chunks[base];offset=self.position-base
            part=chunk[offset:offset+min(stop-self.position,len(chunk)-offset)]
            if not part:raise OSError('Source range unexpectedly empty')
            parts.append(part);self.position+=len(part)
        return b''.join(parts)
    def readinto(self,buffer):
        value=self.read(len(buffer));buffer[:len(value)]=value;return len(value)
    def close(self):
        if not self.closed:
            self.cache.clear()
            if self.owns_client:self.client.close()
        super().close()


def range_opener(path,mode='rb'):
    if mode not in ('r','rb'):raise OSError('Source is read-only')
    if not str(path).endswith('.tif'):raise FileNotFoundError(path)
    return HTTPRangeReader(str(path),cache_dir=Path(__file__).resolve().parents[1]/'storage'/'monitoring-city'/'http-ranges')
