"""Validate a Colab result and prepare browser assets; never deserialize PyTorch pickles."""
from pathlib import Path
import argparse, ast, hashlib, json, shutil, tempfile, zipfile
import numpy as np
import onnxruntime as ort

CLASSES=['phone','cigarette','seatbelt_on','seatbelt_off']
def install(bundle, project):
    project=Path(project).resolve()
    if not (project/'web/package.json').is_file(): raise ValueError('Not a DriverGuard project folder')
    with tempfile.TemporaryDirectory(prefix='driverguard-candidate-') as temp:
        root=Path(temp)
        with zipfile.ZipFile(bundle) as z:
            if sum(i.file_size for i in z.infolist())>500*1024**2:raise ValueError('Bundle exceeds 500 MB')
            required=['run.json','compatibility.json','metrics.json','dataset_audit.json','driverguard-candidate.onnx']
            for name in required:
                hits=[i for i in z.infolist() if Path(i.filename).name==name and not i.is_dir()]
                if len(hits)!=1:raise ValueError(f'Expected exactly one {name}')
                (root/name).write_bytes(z.read(hits[0]))
        run=json.loads((root/'run.json').read_text(encoding='utf-8'))
        compat=json.loads((root/'compatibility.json').read_text(encoding='utf-8'))
        metrics=json.loads((root/'metrics.json').read_text(encoding='utf-8'))
        data=json.loads((root/'dataset_audit.json').read_text(encoding='utf-8'))
        path=root/'driverguard-candidate.onnx'
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if run.get('trained') is not True or run.get('onnx_sha256')!=digest:raise ValueError('Training record/hash mismatch')
        if compat.get('onnx_valid') is not True or compat.get('classes')!=CLASSES:raise ValueError('Compatibility check missing')
        if len(metrics.get('test',{}).get('per_class',{}))!=4:raise ValueError('Four-class test metrics missing')
        if any(data.get('counts',{}).get('test',{}).get('images_per_class',{}).get(c,0)<1 for c in CLASSES):raise ValueError('Test coverage missing')
        if path.stat().st_size>50*1024**2:raise ValueError('Model exceeds browser size limit')
        opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
        session=ort.InferenceSession(str(path),opts,providers=['CPUExecutionProvider'])
        if len(session.get_inputs())!=1 or session.get_inputs()[0].shape!=[1,3,640,640]:raise ValueError('Input shape mismatch')
        names=ast.literal_eval(session.get_modelmeta().custom_metadata_map.get('names','{}'))
        if (list(names) if isinstance(names,list) else [names.get(i) for i in range(4)])!=CLASSES:raise ValueError('Model class order mismatch')
        output=session.run(None,{session.get_inputs()[0].name:np.zeros((1,3,640,640),np.float32)})
        if len(output)!=1 or output[0].ndim!=3 or output[0].shape[:2]!=(1,8) or not np.isfinite(output[0]).all():raise ValueError('Output is not compatible')
        dest=project/'web/public/models';dest.mkdir(parents=True,exist_ok=True)
        name=f'driverguard-{digest[:16]}.onnx'
        manifest={'schema':1,'classes':CLASSES,'input_size':640,'sha256':digest,'run_id':run['run_id'],'status':'candidate','model_url':f'/models/{name}'}
        current=dest/'browser-model.json'
        if current.exists():
            previous=current.read_bytes();back=dest/('previous-manifest-'+hashlib.sha256(previous).hexdigest()[:12]+'.json')
            if not back.exists():back.write_bytes(previous)
        shutil.copy2(path,dest/name)
        staged=dest/'browser-model.json.tmp';staged.write_text(json.dumps(manifest,indent=2),encoding='utf-8');staged.replace(current)
        receipt={'installed':True,'run_id':run['run_id'],'sha256':digest,'model_file':name,'test_metrics':metrics['test'],'status':'candidate','real_video_validation':'pending','production_approved':False}
        (project/'ml/browser-candidate-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Candidate checked and prepared. Rebuild the web container. Real-video validation is still required.')
        print('Model SHA-256:',digest)
        return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--project',default=str(Path(__file__).resolve().parents[1]))
    a=p.parse_args();install(a.bundle,a.project)
