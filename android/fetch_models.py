"""Fetch pinned, checksummed model artifacts. No API keys or training required."""
import hashlib,json,urllib.request
from pathlib import Path

def main():
    root=Path(__file__).resolve().parent
    dest=root/'app/src/main/assets';dest.mkdir(parents=True,exist_ok=True)
    for model in json.loads((root/'models.json').read_text(encoding='utf-8'))['models']:
        path=dest/model['file']
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==model['sha256']:
            print(model['file'],'OK');continue
        temp=path.with_suffix(path.suffix+'.partial')
        print('Downloading',model['file'],flush=True)
        with urllib.request.urlopen(model['url'],timeout=120) as src,temp.open('wb') as out:
            while chunk:=src.read(1024*1024): out.write(chunk)
        if temp.stat().st_size!=model['bytes'] or hashlib.sha256(temp.read_bytes()).hexdigest()!=model['sha256']:
            raise RuntimeError('Incomplete or changed model: '+model['file'])
        temp.replace(path)
        print(model['file'],'verified',flush=True)

if __name__=='__main__':main()
