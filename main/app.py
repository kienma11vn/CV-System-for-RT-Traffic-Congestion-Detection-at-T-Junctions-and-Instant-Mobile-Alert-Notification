import cv2
import numpy as np
import time
import threading
import os
import sys
import random
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from ultralytics import YOLO


def resource_path(relative_path):
    """ Lấy đường dẫn tuyệt đối tới tài nguyên, dùng cho môi trường dev và PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
    
def generate_random_location_id(digits=6):
    """Sinh mã vị trí dạng area_{gen} với gen là dãy số ngẫu nhiên"""
    random_num = random.randint(10**(digits-1), (10**digits) - 1)
    return f"area_{random_num}"

# ==================== INTEGRATE FIREBASE FCM ====================
import firebase_admin
from firebase_admin import credentials, messaging, db

FCM_TOPIC = "traffic_alerts" 

def init_firebase(key_path, db_url):
    """Hàm khởi tạo hoặc kết nối lại Firebase từ GUI"""
    if not key_path or not os.path.exists(key_path):
        messagebox.showwarning("Cảnh báo Firebase", f"File key Firebase không hợp lệ hoặc không tồn tại:\n{key_path}")
        return False
    if not db_url:
        messagebox.showwarning("Cảnh báo Firebase", "Vui lòng nhập Database URL Firebase!")
        return False

    try:
        if firebase_admin._apps:
            for app_name, app in list(firebase_admin._apps.items()):
                firebase_admin.delete_app(app)

        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred, {
            'databaseURL': db_url
        })
        print("[FIREBASE INFO] Khởi tạo Firebase Admin SDK & Realtime DB thành công!")
        messagebox.showinfo("Thành công", "Khởi tạo kết nối Firebase thành công!")
        return True
    except Exception as e:
        print(f"[FIREBASE ERROR] Lỗi khởi tạo Firebase: {e}")
        messagebox.showerror("Lỗi Firebase", f"Không thể kết nối Firebase:\n{e}")
        return False


class FCMService:
    def __init__(self, topic=FCM_TOPIC, cooldown_seconds=60, location_id="area_123456", area_name="Ngã ba Cổng Trường"):
        self.topic = topic
        self.cooldown_seconds = cooldown_seconds
        self.location_id = location_id
        self.area_name = area_name
        self.last_sent_time = 0
        self.last_status = "THONG THOANG (NORMAL)"

    def set_location_info(self, location_id, area_name):
        """Cập nhật vị trí ID và Tên khu vực"""
        self.location_id = location_id.strip().replace(" ", "_")
        self.area_name = area_name.strip()

    def sync_realtime_data(self, status, roi_count, stuck_count):
        """Cập nhật dữ liệu Realtime lên Node riêng của Vị trí: traffic_status/{location_id}"""
        def _update():
            if not firebase_admin._apps:
                return
            try:
                ref = db.reference(f'traffic_status/{self.location_id}')
                ref.set({
                    'location_id': str(self.location_id),
                    'area_name': str(self.area_name),
                    'status': str(status),
                    'roi_count': str(roi_count),
                    'stuck_count': str(stuck_count),
                    'timestamp': int(time.time() * 1000)
                })
            except Exception as e:
                pass
        threading.Thread(target=_update, daemon=True).start()

    def send_notification_if_needed(self, current_status, roi_count, stuck_count):
        current_time = time.time()
        
        is_congested = "TAC NGHEN" in current_status
        is_status_changed = (current_status != self.last_status)
        is_cooldown_expired = (current_time - self.last_sent_time) >= self.cooldown_seconds

        if is_congested and (is_status_changed or is_cooldown_expired):
            title = f"⚠️ CẢNH BÁO TẮC NGHỄN: {self.area_name.upper()}"
            body = f"Khu vực [{self.area_name}] ({self.location_id}) đang tắc nghẽn!\n- Số xe kẹt: {stuck_count}/{roi_count} xe."
            
            threading.Thread(
                target=self._push_to_fcm, 
                args=(title, body, current_status, roi_count, stuck_count), 
                daemon=True
            ).start()
            
            self.last_sent_time = current_time
            
        self.last_status = current_status

    def _push_to_fcm(self, title, body, status, roi_count, stuck_count):
        if not firebase_admin._apps:
            return

        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data={
                    'location_id': str(self.location_id),
                    'area_name': str(self.area_name),
                    'status': str(status),
                    'roi_count': str(roi_count),
                    'stuck_count': str(stuck_count),
                    'timestamp': str(int(time.time() * 1000))
                },
                topic=self.topic,
            )
            response = messaging.send(message)
            print(f"[FCM SUCCESS] Đã gửi thông báo TẮC NGHỄN cho {self.area_name} ({self.location_id}): {response}")
        except Exception as e:
            print(f"[FCM ERROR] Gửi thông báo thất bại: {e}")


# ==================== MAIN TRAFFIC APP GUI ====================
DEFAULT_MODEL_PATH = resource_path("model.pt")
CONFIG_FILE = "firebase_config.json"
MAX_CAMERAS = 5
SIDEBAR_WIDTH = 300

class CameraChannel:
    def __init__(self, cam_id):
        self.cam_id = cam_id
        self.name = f"Camera {cam_id + 1}"
        self.location_id = generate_random_location_id(6)
        self.area_name = f"Ngã ba {cam_id + 1}"
        self.fcm_service = FCMService(cooldown_seconds=60, location_id=self.location_id, area_name=self.area_name)
        
        self.model_path = DEFAULT_MODEL_PATH
        self.congestion_threshold = 5
        self.speed_slow_threshold = 5.0
        self.time_stay_threshold = 20.0
        self.alpha = 0.05
        
        # Biến ZOOM & PAN
        self.zoom_factor = 1.0
        self.pan_x = 0  
        self.pan_y = 0  
        self.is_panning = False
        self.last_mouse_x = 0
        self.last_mouse_y = 0

        # ROI mặc định
        self.roi_points = np.array([[150, 250], [500, 250], [600, 450], [50, 450]], np.int32)
        self.is_adjusting_roi = False  
        self.corner_radius_px = 15     
        self.selected_point_idx = None  
        
        self.display_scale_x = 1.0     
        self.display_scale_y = 1.0     
        self.offset_x = 0              
        self.offset_y = 0              

        # Luồng xử lý
        self.tracker_db = {}
        self.running = False
        self.cap = None
        self.thread = None
        self.is_webcam = False
        self.force_finish_video = False 

        # Ghi video
        self.video_writer = None
        self.output_video_path = ""
        
        # Frame kết quả hiện tại
        self.current_frame = None
        self.current_stats = {
            "roi_count": "--",
            "stuck_count": "--",
            "status": "CHƯA KẾT NỐI",
            "status_color": "#7f8c8d"
        }
        
        # Xóa ID khỏi tracker_db nếu không thấy quá 2 giây
        self.tracker_timeout_seconds = 2.0  

class TrafficAppGUI:
    def __init__(self, window):
        self.window = window
        self.window.title("HỆ THỐNG PHÁT HIỆN TẮC NGHỄN GIAO THÔNG - YOLOv8 + FCM Notification (Đa Camera 1-5)")
        self.window.geometry("1380x880") 
        self.window.configure(bg="#2c3e50")

        # Quản lý 5 Channels
        self.channels = [CameraChannel(i) for i in range(MAX_CAMERAS)]
        self.active_cam_idx = 0
        
        # Model YOLOv8 chung
        self.model = None

        # Trạng thái cửa sổ trượt (Left Drawer)
        self.drawer_visible = False
        self.drawer_width = SIDEBAR_WIDTH // 2  # Bằng nửa sidebar cấu hình = 150px

        # Style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("TLabel", background="#2c3e50", foreground="#ecf0f1", font=("Segoe UI", 10))
        self.style.configure("TButton", font=("Segoe UI", 10, "bold"), background="#34495e", foreground="#ecf0f1")
        self.style.map("TButton", background=[('active', '#1abc9c')])

        self.style.configure("Circle.Horizontal.TScale", 
                             background="#34495e", 
                             troughcolor="#1a252f", 
                             sliderlength=18, 
                             borderwidth=0)
        
        self.setup_ui()
        self.load_channel_to_ui(self.active_cam_idx)
        self.load_firebase_saved_config()
        self.start_gui_loop()

    @property
    def current_ch(self):
        return self.channels[self.active_cam_idx]

    def setup_ui(self):
        # Cửa sổ trượt bên trái (Left Drawer) cho danh sách Camera
        self.drawer_frame = tk.Frame(self.window, width=self.drawer_width, bg="#1a252f")
        
        # Header cửa sổ trượt
        drawer_title = tk.Label(self.drawer_frame, text="DANH SÁCH\nCAMERA", bg="#1a252f", fg="#1abc9c", font=("Segoe UI", 10, "bold"))
        drawer_title.pack(pady=10)

        self.cam_buttons = []
        self.cam_status_labels = []

        for i in range(MAX_CAMERAS):
            # Khung chứa cho từng ô Camera
            cam_box = tk.Frame(self.drawer_frame, bg="#1a252f")
            cam_box.pack(fill=tk.X, padx=5, pady=6)

            btn = tk.Button(
                cam_box, 
                text=f"Camera {i+1}", 
                bg="#34495e", 
                fg="white", 
                font=("Segoe UI", 9, "bold"),
                bd=0, 
                height=2,
                command=lambda idx=i: self.select_camera(idx)
            )
            btn.pack(fill=tk.X)

            # Khoảng nhỏ dài ở bên dưới hiển thị OFFLINE hoặc RUNNING và màu cảnh báo tắc nghẽn
            lbl_status = tk.Label(
                cam_box, 
                text="OFFLINE", 
                bg="#7f8c8d", 
                fg="white", 
                font=("Segoe UI", 7, "bold"), 
                height=1
            )
            lbl_status.pack(fill=tk.X, pady=(2, 0))

            self.cam_buttons.append(btn)
            self.cam_status_labels.append(lbl_status)

        # Container chính bên trái chứa Nút Toggle + Sidebar Cấu hình
        self.left_container = tk.Frame(self.window, bg="#2c3e50")
        self.left_container.pack(side=tk.LEFT, fill=tk.Y)

        # Nút bật/tắt Cửa sổ trượt
        self.btn_toggle_drawer = tk.Button(
            self.left_container, 
            text="☰ Chọn Camera", 
            bg="#16a085", 
            fg="white", 
            font=("Segoe UI", 9, "bold"), 
            bd=0,
            command=self.toggle_drawer
        )
        self.btn_toggle_drawer.pack(fill=tk.X, padx=10, pady=(10, 0))

        # Sidebar Cấu hình hệ thống
        sidebar_container = tk.Frame(self.left_container, width=SIDEBAR_WIDTH, bg="#34495e")
        sidebar_container.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        sidebar_container.pack_propagate(False)

        canvas = tk.Canvas(sidebar_container, bg="#34495e", bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(sidebar_container, orient="vertical", command=canvas.yview)
        sidebar = tk.Frame(canvas, bg="#34495e")  

        def on_sidebar_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        sidebar.bind("<Configure>", on_sidebar_configure)
        canvas_window = canvas.create_window((0, 0), window=sidebar, anchor="nw")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.title_lbl = tk.Label(sidebar, text="CẤU HÌNH HỆ THỐNG", font=("Segoe UI", 13, "bold"), bg="#34495e", fg="#1abc9c")
        self.title_lbl.pack(pady=15)

        # Mã Vị trí / Ngã ba (ID)
        loc_frame = tk.Frame(sidebar, bg="#34495e")
        loc_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(loc_frame, text="Mã Ngã ba / Vị trí (ID):", bg="#34495e", fg="#ecf0f1", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        self.entry_location = tk.Entry(loc_frame, font=("Segoe UI", 10, "bold"))
        self.entry_location.pack(fill=tk.X, ipady=3, pady=2)

        # TÊN KHU VỰC
        area_frame = tk.Frame(sidebar, bg="#34495e")
        area_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(area_frame, text="Tên Khu vực / Vị trí:", bg="#34495e", fg="#ecf0f1", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        self.entry_area_name = tk.Entry(area_frame, font=("Segoe UI", 10, "bold"))
        self.entry_area_name.pack(fill=tk.X, ipady=3, pady=2)

        # Model Path
        model_frame = tk.Frame(sidebar, bg="#34495e")
        model_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(model_frame, text="Đường dẫn Weight (YOLO):", bg="#34495e", fg="#ecf0f1", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        self.model_entry = tk.Entry(model_frame, font=("Segoe UI", 9))
        self.model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3, pady=2)
        btn_browse = tk.Button(model_frame, text="...", bg="#1abc9c", fg="white", bd=0, command=self.browse_model, width=3)
        btn_browse.pack(side=tk.RIGHT, padx=5, pady=2)

        # Ngưỡng tắc nghẽn
        tk.Label(sidebar, text="Ngưỡng số xe kẹt đủ điều kiện:", bg="#34495e", fg="#ecf0f1").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.spin_congest = tk.Spinbox(sidebar, from_=1, to=100, font=("Segoe UI", 10))
        self.pack_widget(self.spin_congest)

        # Vận tốc chậm
        tk.Label(sidebar, text="Ngưỡng vận tốc rất chậm (km/h):", bg="#34495e", fg="#ecf0f1").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.entry_speed = tk.Entry(sidebar, font=("Segoe UI", 10))
        self.pack_widget(self.entry_speed)

        # Thời gian đỗ lâu
        tk.Label(sidebar, text="Thời gian đỗ lâu tối đa (giây):", bg="#34495e", fg="#ecf0f1").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.entry_time = tk.Entry(sidebar, font=("Segoe UI", 10))
        self.pack_widget(self.entry_time)

        # ALPHA: Quy đổi số pixel sang mét trên thực tế
        tk.Label(sidebar, text="Hệ số α (mét/pixel):", bg="#34495e", fg="#ecf0f1").pack(anchor=tk.W, padx=10, pady=(10, 0))
        self.entry_alpha = tk.Entry(sidebar, font=("Segoe UI", 10))
        self.pack_widget(self.entry_alpha)

        # NÚT ĐIỀU CHỈNH / XÁC NHẬN ROI
        roi_control_frame = tk.LabelFrame(sidebar, text="QUẢN LÝ ROI", bg="#34495e", fg="#f39c12", font=("Segoe UI", 10, "bold"), padx=5, pady=5)
        roi_control_frame.pack(fill=tk.X, padx=10, pady=8)

        self.btn_toggle_roi = tk.Button(
            roi_control_frame, 
            text="Điều chỉnh ROI", 
            bg="#f39c12", 
            fg="white", 
            font=("Segoe UI", 10, "bold"), 
            bd=0, 
            height=2, 
            command=self.toggle_roi_mode
        )
        self.btn_toggle_roi.pack(fill=tk.X, pady=3)

        instruction_lbl = tk.Label(sidebar, text="- Nhấn 'Điều chỉnh ROI' để bật 4 điểm kéo to ở góc.\n- Khi hoàn tất, nhấn 'Xác nhận ROI' để cố định lại.", 
                                   font=("Segoe UI", 9, "italic"), bg="#34495e", fg="#f1c40f", justify=tk.LEFT, wraplength=280)                           
        instruction_lbl.pack(fill=tk.X, padx=10, pady=4)

        # Zoom & Pan Controls
        zoom_frame = tk.LabelFrame(sidebar, text="ĐIỀU KHIỂN ZOOM & PAN", bg="#34495e", fg="#1abc9c", font=("Segoe UI", 10, "bold"), padx=5, pady=5)
        zoom_frame.pack(fill=tk.X, padx=10, pady=5)

        z_btn_frame = tk.Frame(zoom_frame, bg="#34495e")
        z_btn_frame.pack(fill=tk.X, pady=2)
        
        self.btn_zoom_in = tk.Button(z_btn_frame, text="Zoom In", bg="#16a085", fg="white", font=("Segoe UI", 10, "bold"), bd=0, width=8, command=self.zoom_in)
        self.btn_zoom_in.pack(side=tk.LEFT, padx=2, expand=True)

        self.btn_zoom_out = tk.Button(z_btn_frame, text="Zoom Out", bg="#d35400", fg="white", font=("Segoe UI", 10, "bold"), bd=0, width=8, command=self.zoom_out)
        self.btn_zoom_out.pack(side=tk.LEFT, padx=2, expand=True)

        self.btn_zoom_reset = tk.Button(z_btn_frame, text="Reset", bg="#7f8c8d", fg="white", font=("Segoe UI", 10, "bold"), bd=0, width=8, command=self.zoom_reset)
        self.btn_zoom_reset.pack(side=tk.LEFT, padx=2, expand=True)

        self.lbl_zoom_status = tk.Label(sidebar, text="Tỷ lệ thu phóng: 100%", font=("Segoe UI", 9, "italic"), bg="#34495e", fg="#ecf0f1")

        self.zoom_slider = ttk.Scale(
            zoom_frame, 
            from_=1.0, 
            to=4.0, 
            orient=tk.HORIZONTAL, 
            style="Circle.Horizontal.TScale",
            command=self.on_zoom_slider_change
        )
        self.zoom_slider.set(1.0)
        self.zoom_slider.pack(fill=tk.X, padx=5, pady=8)

        pad_frame = tk.Frame(zoom_frame, bg="#34495e")
        pad_frame.pack(pady=5)

        tk.Button(pad_frame, text="▲", bg="#2c3e50", fg="white", width=4, command=lambda: self.pan_move(0, -0.1)).grid(row=0, column=1, pady=1)
        tk.Button(pad_frame, text="◄", bg="#2c3e50", fg="white", width=4, command=lambda: self.pan_move(-0.1, 0)).grid(row=1, column=0, padx=1)
        tk.Button(pad_frame, text="●", bg="#e74c3c", fg="white", width=4, command=self.pan_center).grid(row=1, column=1, padx=1)
        tk.Button(pad_frame, text="►", bg="#2c3e50", fg="white", width=4, command=lambda: self.pan_move(0.1, 0)).grid(row=1, column=2, padx=1)
        tk.Button(pad_frame, text="▼", bg="#2c3e50", fg="white", width=4, command=lambda: self.pan_move(0, 0.1)).grid(row=2, column=1, pady=1)

        self.lbl_zoom_status.pack(pady=2)
        
        zoom_in_text = tk.Label(sidebar, text="- Khi đã Zoom in: Dùng chuột PHẢI (hoặc Nút điều hướng) để di chuyển góc nhìn.", 
                                   font=("Segoe UI", 9, "italic"), bg="#34495e", fg="#f1c40f", justify=tk.LEFT, wraplength=280)                           
        zoom_in_text.pack(fill=tk.X, padx=10, pady=4)

        # Buttons Action
        self.btn_frame = tk.Frame(sidebar, bg="#34495e")
        self.btn_frame.pack(fill=tk.X, padx=10, pady=5)

        self.btn_webcam = tk.Button(self.btn_frame, text="Kết nối Camera", bg="#3498db", fg="white", font=("Segoe UI", 10, "bold"), bd=0, height=2, command=self.start_webcam)
        self.btn_webcam.pack(fill=tk.X, pady=3)

        self.btn_video = tk.Button(self.btn_frame, text="Chọn Video", bg="#e67e22", fg="white", font=("Segoe UI", 10, "bold"), bd=0, height=2, command=self.start_video)
        self.btn_video.pack(fill=tk.X, pady=3)

        self.btn_save = tk.Button(self.btn_frame, text="Lưu Video Output", bg="#2ecc71", fg="white", font=("Segoe UI", 10, "bold"), bd=0, height=2, command=self.handle_save_video)
        self.btn_save.pack(fill=tk.X, pady=3)

        self.btn_stop = tk.Button(self.btn_frame, text="Dừng", bg="#e74c3c", fg="white", font=("Segoe UI", 10, "bold"), bd=0, height=2, command=self.handle_stop)
        self.btn_stop.pack(fill=tk.X, pady=3)

        # ==================== KHU VỰC CẤU HÌNH FIREBASE ====================
        firebase_frame = tk.LabelFrame(sidebar, text="CẤU HÌNH FIREBASE", bg="#34495e", fg="#e67e22", font=("Segoe UI", 10, "bold"), padx=5, pady=5)
        firebase_frame.pack(fill=tk.X, padx=10, pady=8)

        # Textbox chọn File Key Path
        tk.Label(firebase_frame, text="File Key Firebase (JSON):", bg="#34495e", fg="#ecf0f1", font=("Segoe UI", 8, "bold")).pack(anchor=tk.W)
        fb_key_box = tk.Frame(firebase_frame, bg="#34495e")
        fb_key_box.pack(fill=tk.X, pady=2)
        self.entry_firebase_key = tk.Entry(fb_key_box, font=("Segoe UI", 9))
        self.entry_firebase_key.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        btn_browse_fb = tk.Button(fb_key_box, text="...", bg="#1abc9c", fg="white", bd=0, command=self.browse_firebase_key, width=3)
        btn_browse_fb.pack(side=tk.RIGHT, padx=2)

        # Textbox URL Database
        tk.Label(firebase_frame, text="URL Database:", bg="#34495e", fg="#ecf0f1", font=("Segoe UI", 8, "bold")).pack(anchor=tk.W, pady=(5, 0))
        self.entry_database_url = tk.Entry(firebase_frame, font=("Segoe UI", 9))
        self.entry_database_url.pack(fill=tk.X, ipady=2, pady=2)

        # Checkbox Ghi nhớ thông tin kết nối Firebase
        self.remember_fb_var = tk.BooleanVar(value=False)
        self.chk_remember_fb = tk.Checkbutton(
            firebase_frame,
            text="Ghi nhớ File JSON và URL",
            variable=self.remember_fb_var,
            bg="#34495e",
            fg="#ecf0f1",
            selectcolor="#2c3e50",
            activebackground="#34495e",
            activeforeground="#ecf0f1",
            font=("Segoe UI", 8, "bold")
        )
        self.chk_remember_fb.pack(anchor=tk.W, pady=(3, 3))

        # Nút xác nhận kết nối Firebase
        self.btn_init_fb = tk.Button(
            firebase_frame, 
            text="Kết nối Firebase", 
            bg="#e67e22", 
            fg="white", 
            font=("Segoe UI", 9, "bold"), 
            bd=0, 
            height=1, 
            command=self.handle_connect_firebase
        )
        self.btn_init_fb.pack(fill=tk.X, pady=5)

        # Right Panel
        main_panel = tk.Frame(self.window, bg="#2c3e50")
        main_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.stats_frame = tk.Frame(main_panel, bg="#2c3e50")
        self.stats_frame.pack(fill=tk.X, pady=(0, 10))

        self.lbl_stat_in_roi = tk.Label(self.stats_frame, text="Số xe trong ROI: --", font=("Segoe UI", 12, "bold"), bg="#2980b9", fg="white", padx=15, pady=8)
        self.lbl_stat_in_roi.pack(side=tk.LEFT, padx=5)

        self.lbl_stat_stuck = tk.Label(self.stats_frame, text="Số xe bị kẹt: --", font=("Segoe UI", 12, "bold"), bg="#d35400", fg="white", padx=15, pady=8)
        self.lbl_stat_stuck.pack(side=tk.LEFT, padx=5)

        self.lbl_stat_status = tk.Label(self.stats_frame, text="Trạng thái: CHƯA KẾT NỐI", font=("Segoe UI", 12, "bold"), bg="#7f8c8d", fg="white", padx=15, pady=8)
        self.lbl_stat_status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.view_screen = tk.Label(main_panel, bg="#1a252f", text="Không có tín hiệu camera", fg="#7f8c8d", font=("Segoe UI", 12))
        self.view_screen.pack(fill=tk.BOTH, expand=True)

        self.view_screen.bind("<Button-1>", self.on_mouse_click)
        self.view_screen.bind("<B1-Motion>", self.on_mouse_drag)
        self.view_screen.bind("<ButtonRelease-1>", self.on_mouse_release)
        
        self.view_screen.bind("<Button-3>", self.on_pan_start)
        self.view_screen.bind("<B3-Motion>", self.on_pan_drag)
        self.view_screen.bind("<ButtonRelease-3>", self.on_pan_stop)

    # ------------------- LOGIC CẤU HÌNH BỘ NHỚ FIREBASE -------------------
    def load_firebase_saved_config(self):
        """ Tải thông tin Firebase đã lưu nếu có file cấu hình """
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    key_path = data.get("key_path", "")
                    db_url = data.get("db_url", "")
                    remember = data.get("remember", False)

                    if remember:
                        self.entry_firebase_key.delete(0, tk.END)
                        self.entry_firebase_key.insert(0, key_path)

                        self.entry_database_url.delete(0, tk.END)
                        self.entry_database_url.insert(0, db_url)

                        self.remember_fb_var.set(True)
                    else:
                        self.remember_fb_var.set(False)
            except Exception as e:
                print(f"[CONFIG ERROR] Không thể đọc file cấu hình: {e}")

    def save_firebase_config(self):
        """ Lưu hoặc xóa thông tin Firebase dựa vào trạng thái của Tickbox """
        if self.remember_fb_var.get():
            data = {
                "key_path": self.entry_firebase_key.get().strip(),
                "db_url": self.entry_database_url.get().strip(),
                "remember": True
            }
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"[CONFIG ERROR] Không thể ghi file cấu hình: {e}")
        else:
            if os.path.exists(CONFIG_FILE):
                try:
                    os.remove(CONFIG_FILE)
                except Exception as e:
                    print(f"[CONFIG ERROR] Không thể xóa file cấu hình: {e}")

    # ------------------- DRAWER SLIDING LOGIC -------------------
    def toggle_drawer(self):
        if self.drawer_visible:
            self.drawer_frame.pack_forget()
            self.btn_toggle_drawer.config(bg="#16a085")
            self.drawer_visible = False
        else:
            self.drawer_frame.pack(side=tk.LEFT, fill=tk.Y, before=self.left_container)
            self.btn_toggle_drawer.config(bg="#e74c3c")
            self.drawer_visible = True

    def select_camera(self, idx):
        # Lưu lại cấu hình UI hiện tại vào channel cũ
        self.save_ui_to_channel(self.active_cam_idx)
        
        # Đổi channel active
        self.active_cam_idx = idx
        self.load_channel_to_ui(idx)

    def load_channel_to_ui(self, idx):
        ch = self.channels[idx]
        
        for i, btn in enumerate(self.cam_buttons):
            if i == idx:
                btn.config(bg="#1abc9c", fg="black")
            else:
                btn.config(bg="#34495e", fg="white")

        self.title_lbl.config(text=f"CẤU HÌNH {ch.name.upper()}")

        self.entry_location.delete(0, tk.END)
        self.entry_location.insert(0, ch.location_id)

        self.entry_area_name.delete(0, tk.END)
        self.entry_area_name.insert(0, ch.area_name)

        self.model_entry.delete(0, tk.END)
        self.model_entry.insert(0, ch.model_path)

        self.spin_congest.delete(0, tk.END)
        self.spin_congest.insert(0, str(ch.congestion_threshold))

        self.entry_speed.delete(0, tk.END)
        self.entry_speed.insert(0, str(ch.speed_slow_threshold))

        self.entry_time.delete(0, tk.END)
        self.entry_time.insert(0, str(ch.time_stay_threshold))

        self.entry_alpha.delete(0, tk.END)
        self.entry_alpha.insert(0, str(ch.alpha))

        self.zoom_slider.set(ch.zoom_factor)
        if self.lbl_zoom_status:
            self.lbl_zoom_status.config(text=f"Tỷ lệ thu phóng: {int(ch.zoom_factor * 100)}%")

        if ch.is_adjusting_roi:
            self.btn_toggle_roi.config(text="Xác nhận ROI", bg="#27ae60")
        else:
            self.btn_toggle_roi.config(text="Điều chỉnh ROI", bg="#f39c12")

    def save_ui_to_channel(self, idx):
        ch = self.channels[idx]
        self.apply_inputs_for_channel(ch)

    # ------------------- HELPER GUI METHODS -------------------
    def pack_widget(self, widget):
        widget.pack(fill=tk.X, padx=10, pady=2)

    def toggle_roi_mode(self):
        ch = self.current_ch
        ch.is_adjusting_roi = not ch.is_adjusting_roi
        if ch.is_adjusting_roi:
            self.btn_toggle_roi.config(text="Xác nhận ROI", bg="#27ae60")
        else:
            self.btn_toggle_roi.config(text="Điều chỉnh ROI", bg="#f39c12")

    def zoom_in(self):
        ch = self.current_ch
        ch.zoom_factor = round(ch.zoom_factor + 0.2, 1)
        if ch.zoom_factor > 4.0:
            ch.zoom_factor = 4.0
        self.zoom_slider.set(ch.zoom_factor)
        if self.lbl_zoom_status:
            self.lbl_zoom_status.config(text=f"Tỷ lệ thu phóng: {int(ch.zoom_factor * 100)}%")

    def zoom_out(self):
        ch = self.current_ch
        ch.zoom_factor = round(ch.zoom_factor - 0.2, 1)
        if ch.zoom_factor < 1.0:
            ch.zoom_factor = 1.0
            self.pan_center()
        self.zoom_slider.set(ch.zoom_factor)
        if self.lbl_zoom_status:
            self.lbl_zoom_status.config(text=f"Tỷ lệ thu phóng: {int(ch.zoom_factor * 100)}%")

    def zoom_reset(self):
        ch = self.current_ch
        ch.zoom_factor = 1.0
        self.pan_center()
        self.zoom_slider.set(ch.zoom_factor)
        if self.lbl_zoom_status:
            self.lbl_zoom_status.config(text="Tỷ lệ thu phóng: 100%")

    def on_zoom_slider_change(self, val):
        ch = self.current_ch
        ch.zoom_factor = round(float(val), 1)
        if ch.zoom_factor <= 1.0:
            self.pan_center()
        if getattr(self, 'lbl_zoom_status', None) is not None:
            self.lbl_zoom_status.config(text=f"Tỷ lệ thu phóng: {int(ch.zoom_factor * 100)}%")

    def pan_move(self, dx, dy):
        ch = self.current_ch
        if ch.zoom_factor > 1.0:
            ch.pan_x = max(-1.0, min(1.0, ch.pan_x + dx))
            ch.pan_y = max(-1.0, min(1.0, ch.pan_y + dy))

    def pan_center(self):
        ch = self.current_ch
        ch.pan_x = 0.0
        ch.pan_y = 0.0

    def on_pan_start(self, event):
        ch = self.current_ch
        if ch.zoom_factor > 1.0:
            ch.is_panning = True
            ch.last_mouse_x = event.x
            ch.last_mouse_y = event.y

    def on_pan_drag(self, event):
        ch = self.current_ch
        if ch.is_panning and ch.zoom_factor > 1.0:
            dx = event.x - ch.last_mouse_x
            dy = event.y - ch.last_mouse_y
            
            ch.pan_x -= (dx / 300.0) / ch.zoom_factor
            ch.pan_y -= (dy / 300.0) / ch.zoom_factor
            
            ch.pan_x = max(-1.0, min(1.0, ch.pan_x))
            ch.pan_y = max(-1.0, min(1.0, ch.pan_y))
            
            ch.last_mouse_x = event.x
            ch.last_mouse_y = event.y

    def on_pan_stop(self, event):
        self.current_ch.is_panning = False

    def browse_model(self):
        file_selected = filedialog.askopenfilename(filetypes=[("PyTorch Weights", "*.pt"), ("All Files", "*.*")])
        if file_selected:
            self.model_entry.delete(0, tk.END)
            self.model_entry.insert(0, file_selected)

    def browse_firebase_key(self):
        file_selected = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if file_selected:
            self.entry_firebase_key.delete(0, tk.END)
            self.entry_firebase_key.insert(0, file_selected)

    def handle_connect_firebase(self):
        key_path = self.entry_firebase_key.get().strip()
        db_url = self.entry_database_url.get().strip()
        
        success = init_firebase(key_path, db_url)
        if success:
            self.save_firebase_config()

    def apply_inputs_for_channel(self, ch):
        try:
            loc = self.entry_location.get().strip()
            area = self.entry_area_name.get().strip()
            
            if not loc:
                messagebox.showerror("Lỗi dữ liệu", "Vui lòng nhập Mã Ngã ba / Vị trí (ID)!")
                return False
            if not area:
                messagebox.showerror("Lỗi dữ liệu", "Vui lòng nhập Tên Khu vực!")
                return False

            ch.location_id = loc
            ch.area_name = area
            ch.fcm_service.set_location_info(ch.location_id, ch.area_name)

            ch.model_path = self.model_entry.get()
            ch.congestion_threshold = int(self.spin_congest.get())
            ch.speed_slow_threshold = float(self.entry_speed.get())
            ch.time_stay_threshold = float(self.entry_time.get())
            ch.alpha = float(self.entry_alpha.get())
            return True
        except ValueError:
            messagebox.showerror("Lỗi dữ liệu", "Vui lòng nhập định dạng số hợp lệ!")
            return False

    def apply_inputs(self):
        return self.apply_inputs_for_channel(self.current_ch)

    def load_model_if_needed(self):
        if self.model is None:
            self.lbl_stat_status.config(text="Đang tải Model YOLOv8...", bg="#f1c40f")
            self.window.update()
            try:
                self.model = YOLO(self.current_ch.model_path)
            except Exception as e:
                messagebox.showerror("Lỗi tải Model", f"Không thể tải file weight: {str(e)}")
                self.lbl_stat_status.config(text="LỖI TẢI MODEL", bg="#e74c3c")
                return False
        return True

    def start_webcam(self):
        ch = self.current_ch
        if not self.apply_inputs() or not self.load_model_if_needed():
            return
        self.stop_processing_immediately(ch)
        ch.is_webcam = True
        ch.force_finish_video = False
        ch.cap = cv2.VideoCapture(0)
        self.init_default_roi_if_needed(ch)
        self.start_thread(ch)

    def start_video(self):
        ch = self.current_ch
        if not self.apply_inputs() or not self.load_model_if_needed():
            return
        video_path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.avi *.mkv"), ("All Files", "*.*")])
        if video_path:
            self.stop_processing_immediately(ch)
            ch.is_webcam = False
            ch.force_finish_video = False
            ch.cap = cv2.VideoCapture(video_path)
            self.init_default_roi_if_needed(ch)
            self.start_thread(ch)

    def handle_save_video(self):
        ch = self.current_ch
        if not ch.running or ch.cap is None:
            messagebox.showwarning("Cảnh báo", f"Hệ thống chưa chạy video trên {ch.name}!")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4"), ("AVI Video", "*.avi"), ("All Files", "*.*")],
            title=f"Chọn nơi lưu Video Output cho {ch.name}"
        )
        
        if file_path:
            ch.output_video_path = file_path
            width = int(ch.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(ch.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = ch.cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or fps > 100: 
                fps = 25.0
                
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            ch.video_writer = cv2.VideoWriter(ch.output_video_path, fourcc, fps, (width, height))
            messagebox.showinfo("Thành công", f"Video {ch.name} sẽ lưu tại:\n{file_path}")

    def handle_stop(self):
        ch = self.current_ch
        if ch.running:
            ch.running = False  
            self.btn_stop.config(state=tk.DISABLED, text="Đang dừng...")

    def update_btn_save_progress(self, progress_val):
        bar_length = 8
        filled_length = int(bar_length * progress_val // 100)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        self.btn_save.config(text=f"Ghi: {bar} {progress_val}%")

    def init_default_roi_if_needed(self, ch):
        if ch.cap is not None:
            ret, frame = ch.cap.read()
            if ret:
                h, w = frame.shape[:2]
                ch.roi_points = np.array([
                    [int(w * 0.2), int(h * 0.5)], 
                    [int(w * 0.8), int(h * 0.5)], 
                    [int(w * 0.95), int(h * 0.9)], 
                    [int(w * 0.05), int(h * 0.9)]
                ], np.int32)
                ch.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def start_thread(self, ch):
        ch.running = True
        ch.tracker_db = {}
        if ch == self.current_ch:
            self.btn_save.config(text="Lưu Video Output") 
        ch.thread = threading.Thread(target=self.video_processing_loop, args=(ch,), daemon=True)
        ch.thread.start()

    def stop_processing_immediately(self, ch):
        if ch.cap is not None:
            ch.cap.release()
            ch.cap = None
            
        if ch.video_writer is not None:
            ch.video_writer.release()
            ch.video_writer = None
            
        ch.running = False
        ch.current_frame = None
        ch.current_stats = {
            "roi_count": "--",
            "stuck_count": "--",
            "status": "CHƯA KẾT NỐI",
            "status_color": "#7f8c8d"
        }

        if ch == self.current_ch:
            self.btn_webcam.config(state=tk.NORMAL)
            self.btn_video.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.NORMAL, text="Dừng")
            self.btn_save.config(text="Lưu Video Output")
            
            self.view_screen.config(image="", text=f"Đã dừng xử lý {ch.name}.")
            self.lbl_stat_status.config(text="CHƯA KẾT NỐI", bg="#7f8c8d")
            self.lbl_stat_in_roi.config(text="Số xe trong ROI: --")
            self.lbl_stat_stuck.config(text="Số xe bị kẹt: --")

    def translate_coords(self, screen_x, screen_y):
        ch = self.current_ch
        if ch.display_scale_x == 0 or ch.display_scale_y == 0:
            return 0, 0
            
        video_x = int((screen_x - ch.offset_x) * ch.display_scale_x)
        video_y = int((screen_y - ch.offset_y) * ch.display_scale_y)
        return video_x, video_y
        
    def get_screen_coords_of_point(self, video_x, video_y):
        ch = self.current_ch
        if ch.display_scale_x == 0 or ch.display_scale_y == 0:
            return 0, 0
            
        screen_x = int(video_x / ch.display_scale_x) + ch.offset_x
        screen_y = int(video_y / ch.display_scale_y) + ch.offset_y
        return screen_x, screen_y

    def on_mouse_click(self, event):
        ch = self.current_ch
        if not ch.is_adjusting_roi or not ch.running or ch.cap is None or ch.force_finish_video:
            return
        
        hit_radius_px = max(ch.corner_radius_px + 10, 25) 
        
        for idx, pt in enumerate(ch.roi_points):
            pt_screen_x, pt_screen_y = self.get_screen_coords_of_point(pt[0], pt[1])
            dist = np.sqrt((pt_screen_x - event.x)**2 + (pt_screen_y - event.y)**2)
            
            if dist <= hit_radius_px:
                ch.selected_point_idx = idx
                break

    def on_mouse_drag(self, event):
        ch = self.current_ch
        if ch.is_adjusting_roi and ch.selected_point_idx is not None and ch.running and not ch.force_finish_video:
            drag_x, drag_y = self.translate_coords(event.x, event.y)
            if ch.cap is not None:
                video_w = int(ch.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                video_h = int(ch.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                
                drag_x = max(0, min(drag_x, video_w - 1))
                drag_y = max(0, min(drag_y, video_h - 1))
                
                ch.roi_points[ch.selected_point_idx] = [drag_x, drag_y]

    def on_mouse_release(self, event):
        self.current_ch.selected_point_idx = None

    # ------------------- PROCESSING LOOP -------------------
    def video_processing_loop(self, ch):
        total_frames = 0
        if ch.cap is not None and not ch.is_webcam:
            total_frames = int(ch.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        while ch.running and ch.cap is not None:
            ret, frame = ch.cap.read()
            if not ret:
                break
            
            processed_frame, stats = self.process_core_logic(ch, frame)

            if ch.video_writer is not None:
                ch.video_writer.write(processed_frame)
                if total_frames > 0 and ch == self.current_ch:
                    current_frame = int(ch.cap.get(cv2.CAP_PROP_POS_FRAMES))
                    progress = min(100, int((current_frame / total_frames) * 100))
                    self.window.after(0, self.update_btn_save_progress, progress)

            if ch.force_finish_video:
                continue

            # Lưu lại dữ liệu xử lý để GUI Thread hiển thị camera đang chọn
            ch.current_frame = processed_frame
            ch.current_stats = stats
            time.sleep(0.01)

        out_path = ch.output_video_path
        has_finished_file = ch.video_writer is not None and not ch.is_webcam
        
        self.window.after(0, lambda: self.stop_processing_immediately(ch))
        
        if has_finished_file and out_path:
            self.window.after(0, lambda: messagebox.showinfo("Xuất Video Thành Công", f"Video {ch.name} xuất tại:\n{out_path}"))

    def start_gui_loop(self):
        """ Vòng lặp cập nhật giao diện hiển thị camera đang được chọn và tình trạng Sidebar """
        
        # Cập nhật nhãn trạng thái OFFLINE / RUNNING
        for i, ch in enumerate(self.channels):
            lbl_status = self.cam_status_labels[i]
            if ch.running:
                lbl_status.config(
                    text="RUNNING",
                    bg=ch.current_stats["status_color"]
                )
            else:
                lbl_status.config(
                    text="OFFLINE",
                    bg="#7f8c8d"
                )

        # Cập nhật màn hình chính bên phải cho Camera đang active
        ch = self.current_ch
        if ch.running and ch.current_frame is not None:
            processed_frame = ch.current_frame.copy()
            h, w = processed_frame.shape[:2]
            screen_w = self.view_screen.winfo_width()
            screen_h = self.view_screen.winfo_height()
            
            if screen_w > 10 and screen_h > 10:
                ratio = min(screen_w / w, screen_h / h)
                new_w = int(w * ratio)
                new_h = int(h * ratio)
                
                ch.display_scale_x = w / new_w
                ch.display_scale_y = h / new_h
                ch.offset_x = (screen_w - new_w) // 2
                ch.offset_y = (screen_h - new_h) // 2
                
                processed_frame = cv2.resize(processed_frame, (new_w, new_h))

            rgb_image = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_image)
            img_tk = ImageTk.PhotoImage(image=pil_image)

            self.view_screen.config(image=img_tk, text="")
            self.view_screen.image = img_tk  

            self.lbl_stat_in_roi.config(text=f"Số xe trong ROI: {ch.current_stats['roi_count']}")
            self.lbl_stat_stuck.config(text=f"Số xe bị kẹt: {ch.current_stats['stuck_count']}")
            self.lbl_stat_status.config(text=f"[{ch.location_id}] Trạng thái: {ch.current_stats['status']}", bg=ch.current_stats['status_color'])
        else:
            # Nếu camera đang chọn chưa chạy (OFFLINE), lập tức reset màn hình chính
            self.view_screen.config(image="", text=f"Chưa có tín hiệu từ {ch.name}")
            self.view_screen.image = None
            self.lbl_stat_in_roi.config(text="Số xe trong ROI: --")
            self.lbl_stat_stuck.config(text="Số xe bị kẹt: --")
            self.lbl_stat_status.config(text=f"[{ch.location_id}] Trạng thái: CHƯA KẾT NỐI", bg="#7f8c8d")

        self.window.after(30, self.start_gui_loop)

    def process_core_logic(self, ch, frame):
        h, w = frame.shape[:2]
        
        if ch.zoom_factor > 1.0:
            crop_w = int(w / ch.zoom_factor)
            crop_h = int(h / ch.zoom_factor)
            
            max_pan_x = (w - crop_w) // 2
            max_pan_y = (h - crop_h) // 2
            
            cx = (w // 2) + int(ch.pan_x * max_pan_x)
            cy = (h // 2) + int(ch.pan_y * max_pan_y)
            
            x1 = max(0, min(w - crop_w, cx - crop_w // 2))
            y1 = max(0, min(h - crop_h, cy - crop_h // 2))
            x2 = x1 + crop_w
            y2 = y1 + crop_h
            
            crop_img = frame[y1:y2, x1:x2]
            frame = cv2.resize(crop_img, (w, h))

        current_time = time.time()
        results = self.model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)[0]
        
        vehicles_in_roi = 0
        vehicles_congested_in_roi = 0
        
        cv2.polylines(frame, [ch.roi_points], isClosed=True, color=(255, 255, 0), thickness=2)
        
        if ch.is_adjusting_roi:
            r_x = int(ch.corner_radius_px * ch.display_scale_x)
            r_y = int(ch.corner_radius_px * ch.display_scale_y)
            radius = max(r_x, r_y, 10)

            for idx, pt in enumerate(ch.roi_points):
                circle_color = (0, 0, 255) if idx == ch.selected_point_idx else (0, 255, 0)
                cv2.circle(frame, (pt[0], pt[1]), radius, circle_color, -1)
                cv2.circle(frame, (pt[0], pt[1]), radius + 2, (255, 255, 255), 2)

        active_ids_this_frame = set()
        
        if results.boxes is not None and results.boxes.id is not None:
            boxes = results.boxes.xyxy.cpu().numpy()
            track_ids = results.boxes.id.cpu().int().numpy()
            confidences = results.boxes.conf.cpu().numpy()
            classes = results.boxes.cls.cpu().int().numpy()
            
            for box, track_id, conf, cls in zip(boxes, track_ids, confidences, classes):
                x1_b, y1_b, x2_b, y2_b = map(int, box)
                label = results.names[cls]
                active_ids_this_frame.add(track_id)
                
                cx = (x1_b + x2_b) // 2
                cy = int(y2_b)
                
                inside_roi = cv2.pointPolygonTest(ch.roi_points, (cx, cy), False)
                stay_duration = 0.0
                
                if inside_roi >= 0:
                    vehicles_in_roi += 1
                    
                    if track_id not in ch.tracker_db:
                        ch.tracker_db[track_id] = {
                            'first_seen': current_time,
                            'last_seen': current_time,
                            'last_pos': (cx, cy),
                            'speed': 25.0
                        }
                    else:
                        car_data = ch.tracker_db[track_id]
                        dt = current_time - car_data['last_seen']
                        stay_duration = current_time - car_data['first_seen']
                        
                        prev_cx, prev_cy = car_data['last_pos']
                        pixel_dist = np.sqrt((cx - prev_cx)**2 + (cy - prev_cy)**2)
                        
                        if dt > 0.05:
                            dist_meters = pixel_dist * ch.alpha
                            speed_mps = dist_meters / dt
                            speed_kmh = speed_mps * 3.6
                            current_speed_kmh = car_data['speed'] * 0.7 + speed_kmh * 0.3
                        else:
                            current_speed_kmh = car_data['speed']
                            
                        ch.tracker_db[track_id]['last_seen'] = current_time
                        ch.tracker_db[track_id]['last_pos'] = (cx, cy)
                        ch.tracker_db[track_id]['speed'] = current_speed_kmh
                    
                    if ch.tracker_db[track_id]['speed'] < ch.speed_slow_threshold and stay_duration > ch.time_stay_threshold:
                        vehicles_congested_in_roi += 1
                        box_color = (0, 0, 255) 
                    else:
                        box_color = (0, 165, 255) 
                else:
                    box_color = (0, 255, 0) 
                    # Vẫn cập nhật last_seen để không bị xóa nhầm do mất detection ngắn hạn
                    if track_id in ch.tracker_db:
                        ch.tracker_db[track_id]['last_seen'] = current_time
                
                cv2.rectangle(frame, (x1_b, y1_b), (x2_b, y2_b), box_color, 2)
                if inside_roi >= 0 and track_id in ch.tracker_db:
                    info_label = f"ID:{track_id} {label} | {ch.tracker_db[track_id]['speed']:.1f}km/h | {stay_duration:.1f}s"
                else:
                    info_label = f"ID:{track_id} {label} {conf:.2f}"
                    
                cv2.putText(frame, info_label, (x1_b, y1_b - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, box_color, 1)
        
        # Dọn dẹp các ID đã mất tích quá thời gian timeout (giúp giải phóng bộ nhớ an toàn)
        timeout_threshold = getattr(ch, 'tracker_timeout_seconds', 2.0)
        stale_ids = [
            tid for tid, data in ch.tracker_db.items()
            if (current_time - data['last_seen']) > timeout_threshold
        ]
        for tid in stale_ids:
            del ch.tracker_db[tid]
                
        # ================= LOGIC PHÂN LOẠI TRẠNG THÁI =================
        if vehicles_in_roi >= ch.congestion_threshold and vehicles_congested_in_roi >= ch.congestion_threshold:
            status = "TAC NGHEN (CONGESTION)"
            status_color_bgr = (43, 57, 192) 
            status_text_color = (255, 255, 255)
            status_gui_color = "#c0392b"
        elif vehicles_in_roi >= ch.congestion_threshold:
            status = "PHUONG TIEN DONG (HEAVY TRAFFIC)"
            status_color_bgr = (0, 84, 211) 
            status_text_color = (255, 255, 255)
            status_gui_color = "#d35400"
        else:
            status = "THONG THOANG (NORMAL)"
            status_color_bgr = (96, 174, 39) 
            status_text_color = (255, 255, 255)
            status_gui_color = "#27ae60"

        # ================= GỬI DATA REALTIME & PUSH NOTIFICATION =================
        ch.fcm_service.sync_realtime_data(status, vehicles_in_roi, vehicles_congested_in_roi)
        ch.fcm_service.send_notification_if_needed(status, vehicles_in_roi, vehicles_congested_in_roi)

        # ================= HIỂN THỊ THÔNG TIN VỪA ĐỦ LÊN VIDEO =================
        cv2.rectangle(frame, (10, 10), (430, 120), (30, 30, 30), -1)
        cv2.rectangle(frame, (10, 10), (430, 120), (100, 100, 100), 2)
        
        cv2.putText(frame, f"MA ID: {ch.location_id.upper()}", (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(frame, f"So xe trong ROI: {vehicles_in_roi}", (20, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (245, 128, 41), 2)
        cv2.putText(frame, f"So xe bi ket: {vehicles_congested_in_roi}", (20, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
        
        cv2.rectangle(frame, (20, 85), (420, 112), status_color_bgr, -1)
        cv2.putText(frame, f"STATUS: {status}", (25, 103), cv2.FONT_HERSHEY_SIMPLEX, 0.43, status_text_color, 2)

        stats_res = {
            "roi_count": vehicles_in_roi,
            "stuck_count": vehicles_congested_in_roi,
            "status": status,
            "status_color": status_gui_color
        }
        return frame, stats_res

if __name__ == "__main__":
    root = tk.Tk()
    app = TrafficAppGUI(root)
    root.mainloop()