
import cv2
import torch
import torch.nn as nn
from torchvision import models, transforms
import numpy as np
import os
import time

# --- CONFIGURATION ---
MODEL_PATH = '/home/ladliju/Developer/Model_finetune/line_classifier.pth'
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
CLASS_NAMES = ['Move Left', 'Move Right', 'No Line', 'Straight', 'Turn Left', 'Turn Right']
IMG_SIZE = 224

# Transformation pipeline
tf = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

def load_model():
    print(f"[*] Loading model from: {MODEL_PATH}")
    if not os.path.exists(MODEL_PATH):
        print(f" [!] ERROR: File not found at {MODEL_PATH}")
        return None
    
    try:
        model = models.mobilenet_v2(weights=None)
        model.classifier = nn.Sequential(
            nn.Dropout(p=0.3),
            nn.Linear(model.last_channel, len(CLASS_NAMES))
        )
        checkpoint = torch.load(MODEL_PATH, map_location=DEVICE)
        
        # Handle different checkpoint formats
        if 'model_state' in checkpoint:
            model.load_state_dict(checkpoint['model_state'])
        else:
            model.load_state_dict(checkpoint)
            
        model.eval().to(DEVICE)
        acc = checkpoint.get('val_acc', 'N/A')
        print(f" [V] Model Loaded Successfully! (Stored Accuracy: {acc})")
        return model
    except Exception as e:
        print(f" [!] FAILED to load model: {e}")
        return None

def test_inference():
    model = load_model()
    if model is None: return

    print("[*] Opening Camera...")
    cap = cv2.VideoCapture(0) # Default laptop webcam
    if not cap.isOpened():
        print(" [!] ERROR: Cannot open webcam")
        return

    print("\n[RUNNING] Press 'q' to quit")
    
    last_time = time.time()
    
    while True:
        ret, frame = cap.read()
        if not ret: break

        # Preprocess
        tensor = tf(frame).unsqueeze(0).to(DEVICE)
        
        # Inference
        with torch.no_grad():
            output = model(tensor)
            probs = torch.softmax(output, dim=1)
            conf, pred = probs.max(dim=1)
        
        label = CLASS_NAMES[pred.item()]
        confidence = conf.item() * 100

        # Draw UI
        display = frame.copy()
        color = (0, 255, 0) if "Straight" in label else (255, 0, 255)
        if "No Line" in label: color = (0, 0, 255)

        # Header
        cv2.rectangle(display, (0, 0), (display.shape[1], 60), (20, 20, 20), -1)
        cv2.putText(display, f"LFR ML TEST | {label}", (20, 40), 
                    cv2.FONT_HERSHEY_DUPLEX, 0.8, color, 2)
        
        # Confidence Bar
        bar_w = int(confidence * 2)
        cv2.rectangle(display, (20, 70), (20 + bar_w, 85), color, -1)
        cv2.putText(display, f"{confidence:.1f}%", (20 + bar_w + 10, 83), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # FPS
        fps = 1.0 / (time.time() - last_time)
        last_time = time.time()
        cv2.putText(display, f"FPS: {fps:.1f}", (display.shape[1] - 100, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

        cv2.imshow("LFR ML Debugger", display)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[*] Test Stopped.")

if __name__ == "__main__":
    test_inference()
