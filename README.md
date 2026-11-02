# Computer Vision System for Real-time Traffic Congestion Detection at T-Junctions and Instant Mobile Alert Notification

Hệ thống dùng thị giác máy tính để phát hiện phương tiện và tình trạng ùn tắc tại các nút giao ngã ba (chữ T). Ứng dụng Desktop xử lý webcam hoặc video, đồng bộ trạng thái lên Firebase Realtime Database và gửi cảnh báo qua Firebase Cloud Messaging (FCM). Ứng dụng Android hiển thị tình hình các khu vực và nhận thông báo trên điện thoại.

---

## 1. Giới thiệu

Hệ thống gồm ba thành phần:

1. **Ứng dụng Desktop** (`main/app.py`): giao diện Python/Tkinter, dùng mô hình YOLO trong `main/model.pt` để phát hiện phương tiện và ByteTrack để theo dõi ID qua các khung hình. Hỗ trợ tối đa 5 kênh camera, nhận nguồn webcam hoặc tệp video, tùy chỉnh vùng quan sát (ROI) và hiển thị số xe trong vùng, số xe bị kẹt cùng trạng thái giao thông.
2. **Firebase**: Realtime Database lưu trạng thái từng khu vực; FCM gửi cảnh báo đến topic `traffic_alerts`. Khi phát hiện ùn tắc, hệ thống gửi cảnh báo và áp dụng khoảng nghỉ 60 giây để hạn chế thông báo lặp.
3. **Ứng dụng Android** (`mobile/`): đọc dữ liệu Realtime Database theo thời gian thực, cho phép tìm kiếm/chọn camera, xem số liệu và bật/tắt nhận cảnh báo toàn cục hoặc theo từng camera.

Các trạng thái và số liệu được đồng bộ dưới `traffic_status/{location_id}`. Ứng dụng Android chỉ hiển thị camera có cập nhật trong vòng 15 giây gần nhất.

---

## 2. Cài đặt ban đầu

### 2.1. Ứng dụng desktop

Yêu cầu: Windows, Python 3.10 trở lên, kết nối Internet để cài thư viện và tải các thành phần mô hình lần đầu. Tkinter thường có sẵn trong bộ cài Python cho Windows.

Mở PowerShell tại thư mục dự án và chạy:

```powershell
cd main
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Nếu PowerShell không cho phép kích hoạt môi trường ảo, có thể gọi trực tiếp trình thông dịch của môi trường:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Giữ `model.pt` cùng thư mục với `app.py` như hiện tại. Chạy ứng dụng từ thư mục `main` để đường dẫn mô hình và tệp cấu hình Firebase được phân giải đúng. Tệp cấu hình runtime `firebase_config.json` được ứng dụng tạo tại thư mục làm việc hiện tại.

### 2.2. Ứng dụng Android

Yêu cầu: Android Studio, Android SDK phù hợp với cấu hình dự án (compile/target SDK 34), JDK tương thích với Gradle/Android Gradle Plugin. Ứng dụng hỗ trợ Android 7.0 (API 24) trở lên. Cần cấp quyền thông báo trên Android 13 trở lên.

1. Mở thư mục `mobile` bằng Android Studio và chờ Gradle đồng bộ.
2. Thiết lập Firebase theo mục 3 bên dưới.
3. Chạy cấu hình `app` trên thiết bị hoặc emulator có Google Play services; hoặc tạo APK debug từ PowerShell:

```powershell
cd mobile
.\gradlew.bat assembleDebug
```

APK debug được tạo tại `mobile/app/build/outputs/apk/debug/app-debug.apk`.

---

## 3. Thiết lập Firebase và kết nối

Desktop dùng Firebase Admin SDK với khóa tài khoản dịch vụ. Android dùng Firebase Android SDK và tệp cấu hình ứng dụng. Cả hai phải trỏ đến **cùng một Firebase project và Realtime Database**.

### 3.1. Tạo Firebase project và Realtime Database

1. Tạo project tại [Firebase Console](https://console.firebase.google.com/).
2. Trong **Build → Realtime Database**, tạo database và chọn region phù hợp.
3. Sao chép URL database được Firebase cung cấp, ví dụ:
   - `https://<project-id>-default-rtdb.firebaseio.com/`
   - hoặc `https://<project-id>.<region>.firebasedatabase.app/`

   Dùng chính xác URL trong trang Realtime Database; không thay bằng URL Firebase project hoặc Storage bucket.
4. Kiểm tra **Rules** trước khi chạy. Ứng dụng Android hiện đọc Realtime Database trực tiếp và không đăng nhập bằng Firebase Authentication; nếu rules yêu cầu người dùng đã xác thực, ứng dụng hiện tại sẽ không đọc được dữ liệu. Chỉ trong môi trường thử nghiệm cô lập mới cân nhắc tạm thời cho phép đọc dữ liệu, không cho phép ghi công khai và không dùng dữ liệu nhạy cảm. Không để rules công khai trong môi trường triển khai; cần bổ sung cơ chế xác thực và rules phù hợp trước khi phát hành.
   - Ví dụ **Rules**: 
   ```json
   {
     "rules": {
        "traffic_status": {
          ".read": true,
          ".write": false
        }
      }
   }
   ```

Ứng dụng desktop ghi dữ liệu JSON theo cấu trúc:

```json
{
  "traffic_status": {
    "area_123456": {
      "location_id": "area_123456",
      "area_name": "Ngã ba 1",
      "status": "THONG THOANG (NORMAL)",
      "roi_count": "8",
      "stuck_count": "0",
      "timestamp": 1762000000000
    }
  }
}
```

`timestamp` là thời gian Unix tính bằng mili giây. Các trường `roi_count` và `stuck_count` được desktop ghi dưới dạng chuỗi.

### 3.2. Cấu hình Firebase cho desktop

1. Trong Firebase Console, mở **Project settings → Service accounts** và tạo khóa riêng tư JSON cho Firebase Admin SDK.
2. Lưu khóa JSON ở vị trí an toàn trên máy chạy ứng dụng desktop. Không đưa khóa này vào Git, không gửi khóa vào ứng dụng Android và không chia sẻ công khai.
3. Khởi chạy desktop, mở phần cấu hình Firebase, chọn **File Key Firebase (JSON)** và trỏ đến khóa vừa tải.
4. Nhập **Database URL** đã sao chép ở mục 3.1, sau đó nhấn **Kết nối Firebase**. Giao diện báo kết nối thành công khi khởi tạo được Admin SDK.
5. Cấu hình kết nối được ghi vào `firebase_config.json` để dùng lại ở lần chạy sau. Hãy bảo vệ tệp này vì nó lưu đường dẫn khóa và URL database; không commit tệp hoặc khóa tài khoản dịch vụ vào repository.

Admin SDK được cấp quyền rộng và không phụ thuộc vào quy tắc bảo mật Realtime Database như ứng dụng client. Chỉ cấp khóa cho máy chủ/desktop tin cậy, giới hạn quyền truy cập tệp và thu hồi khóa nếu bị lộ.

### 3.3. Cấu hình Firebase cho Android

1. Trong Firebase Console, chọn **Add app → Android** và nhập đúng package name: `com.example.trafficjamalert`.
2. Tải `google-services.json` do Firebase tạo cho ứng dụng Android đó và đặt tại `mobile/app/google-services.json` (cùng cấp với `mobile/app/build.gradle.kts`). Không dùng tệp mẫu `google-services.json.example` làm cấu hình kết nối thật.
3. Trong thư mục `mobile`, tạo `local.properties` từ `local.properties.example` nếu tệp này chưa tồn tại. Giữ `sdk.dir` trỏ đến Android SDK cục bộ và thay giá trị URL thành URL Realtime Database của project:

   ```properties
   sdk.dir=C\:\\Users\\<your-user>\\AppData\\Local\\Android\\Sdk
   FIREBASE_DATABASE_URL=https://<your-database-url>/
   ```

   Hãy thay `<your-database-url>` bằng URL thực tế, không giữ dấu ngoặc nhọn.

4. Đồng bộ Gradle và chạy ứng dụng. Khi được hỏi, cho phép thông báo. Ứng dụng tự lắng nghe `traffic_status` và đăng ký topic FCM `traffic_alerts` khi bật nhận cảnh báo.

---

## 4. Cách sử dụng

### Desktop

1. Khởi chạy ứng dụng theo mục 2.1. Kết nối Firebase theo mục 3.2 nếu cần đồng bộ và gửi cảnh báo.
2. Chọn một trong tối đa 5 kênh camera. Nhập tên khu vực để phân biệt các vị trí; mỗi kênh có mã vị trí riêng.
3. Chọn **Kết nối Camera** để dùng webcam hoặc **Chọn Video** để chọn tệp video. Mô hình YOLO được nạp khi bắt đầu xử lý.
4. Điều chỉnh vùng giám sát: nhấn **Điều chỉnh ROI**, kéo bốn đỉnh vùng đa giác đến khu vực cần theo dõi, sau đó nhấn **Xác nhận ROI**.
5. Thay đổi các tham số nếu cần thiết cho phù hợp với từng khu vực giám sát.
6. Theo dõi trạng thái, số xe trong ROI và số xe bị kẹt trên giao diện. Khi Firebase được kết nối, dữ liệu camera được đồng bộ lên Realtime Database; khi có trạng thái tắc nghẽn, hệ thống gửi cảnh báo FCM.
7. Nhấn **Dừng** để ngắt xử lý kênh hiện tại.

Kết quả phụ thuộc vào góc đặt camera, chất lượng hình ảnh, vị trí ROI và hiệu năng máy tính. Nên thử bằng video phù hợp và xác nhận ROI trước khi sử dụng với luồng camera thực tế.

### Android

1. Mở ứng dụng khi desktop đang chạy và đã kết nối Firebase. Danh sách hiển thị các camera đang cập nhật dữ liệu.
2. Chạm vào thẻ camera để xem trạng thái, số xe trong khu vực, số xe bị kẹt và thời điểm cập nhật. Có thể tìm theo mã hoặc tên khu vực.
3. Đánh dấu checkbox trên từng camera để chọn khu vực muốn nhận cảnh báo.
4. Bật công tắc **Trạng thái nhận cảnh báo** để nhận thông báo từ các camera đã chọn; tắt công tắc để dừng nhận. Lựa chọn được lưu trên thiết bị.
5. Cho phép quyền thông báo trong cài đặt Android nếu đã từ chối quyền lúc khởi động.

Thông báo FCM chỉ được hiển thị khi công tắc đang bật, camera tương ứng được chọn và trạng thái gửi về là tắc nghẽn. Ứng dụng áp dụng cooldown 60 giây cho từng địa điểm; desktop cũng có khoảng nghỉ gửi cảnh báo 60 giây.

---

## 5. Khắc phục sự cố

- **Không nạp được mô hình**: xác nhận `model.pt` nằm cạnh `app.py` và chạy ứng dụng từ thư mục `main`.
- **Desktop không kết nối Firebase**: kiểm tra đường dẫn khóa JSON, quyền đọc tệp, Database URL và kết nối Internet; xem thông báo lỗi trên cửa sổ hoặc terminal.
- **Android không hiện camera**: xác nhận `google-services.json` thuộc đúng project và package name, `FIREBASE_DATABASE_URL` chính xác, desktop đang gửi dữ liệu và Realtime Database rules cho phép ứng dụng đọc.
- **Không nhận thông báo**: kiểm tra quyền thông báo, công tắc tổng, checkbox của camera, FCM đã được bật trong Firebase project và thiết bị có Google Play services. Khi thử liên tiếp, chờ hết cooldown 60 giây.
- **Camera biến mất khỏi danh sách**: Android lọc dữ liệu cũ hơn 15 giây; kiểm tra desktop còn xử lý nguồn video/camera và kết nối Firebase.