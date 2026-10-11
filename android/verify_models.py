"""CPU smoke test. This checks executable artifacts, not detection accuracy."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
import onnxruntime as ort

def verify(root):
    report=[]
    for entry in json.loads((root/'models.json').read_text(encoding='utf-8'))['models']:
        path=root/'app/src/main/assets'/entry['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256'],f'Hash mismatch: {path.name}'
        if path.suffix!='.onnx': continue
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        session=ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
        x=np.full(entry['input'],0.5,dtype=np.float32)
        start=time.perf_counter();y=session.run(None,{session.get_inputs()[0].name:x})
        assert all(np.isfinite(a).all() for a in y)
        expected=(1,2) if 'classifier' in path.name else (1,7,8400)
        assert y[0].shape==expected,(path.name,y[0].shape)
        if 'classifier' in path.name: assert abs(float(y[0].sum())-1)<0.001,'Expected probabilities'
        report.append({'file':path.name,'sha256':entry['sha256'],'input':entry['input'],
                       'output':list(y[0].shape),'cpu_ms':round((time.perf_counter()-start)*1000,1),
                       'structural_smoke_pass':True,'field_validated':False})
    return report

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path);args=parser.parse_args()
    result=json.dumps(verify(root),indent=2)
    print(result)
    if args.out:args.out.write_text(result,encoding='utf-8')
