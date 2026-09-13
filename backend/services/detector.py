
from ultralytics import YOLO
from PIL import Image
import io, os, time, uuid
import cv2
import numpy as np

MODEL_URL = os.getenv("POTHOLE_MODEL_URL","https://huggingface.co/peterhdd/pothole-detection-yolov8/resolve/main/best.pt")
MODEL_DIR=os.path.abspath(os.path.join(os.path.dirname(__file__),"..","models"))
MODEL_PATH=os.path.join(MODEL_DIR,"pothole_best.pt")
_model=None

def get_model():
    global _model
    if _model is None:
        os.makedirs(MODEL_DIR,exist_ok=True)
        _model=YOLO(MODEL_PATH if os.path.exists(MODEL_PATH) else MODEL_URL)
    return _model

def detect_potholes(raw, filename):
    img=Image.open(io.BytesIO(raw)).convert("RGB")
    arr=np.array(img)
    model=get_model()
    t=time.perf_counter()
    # Keep inference fast for the prototype: use a fixed inference size and one cached model.
    results=model.predict(source=arr, conf=float(os.getenv("POTHOLE_CONFIDENCE","0.35")), imgsz=int(os.getenv("POTHOLE_IMGSZ","640")), device=os.getenv("POTHOLE_DEVICE","cpu"), max_det=20, verbose=False)
    ms=(time.perf_counter()-t)*1000
    r=results[0]
    detections=[]
    if r.boxes is not None:
        for box, conf, cls in zip(r.boxes.xyxy.cpu().tolist(), r.boxes.conf.cpu().tolist(), r.boxes.cls.cpu().tolist()):
            detections.append({"bbox":[round(v,1) for v in box],"confidence":float(conf),"class_id":int(cls)})
    annotated=r.plot()
    name=f"{uuid.uuid4().hex}_annotated.jpg"
    path=os.path.abspath(os.path.join(os.path.dirname(__file__),"..","evidence",name))
    cv2.imwrite(path, annotated)
    return {"detections":detections,"annotated_path":path,"width":img.width,"height":img.height,"inference_ms":round(ms,1)}
