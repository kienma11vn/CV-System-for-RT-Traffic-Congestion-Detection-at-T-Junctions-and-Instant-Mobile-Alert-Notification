package com.example.trafficjamalert

import android.content.Context
import android.util.Log
import com.google.firebase.database.DataSnapshot
import com.google.firebase.database.DatabaseError
import com.google.firebase.database.FirebaseDatabase
import com.google.firebase.database.ValueEventListener
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// Model lưu thông tin chi tiết từng Camera
data class CameraTrafficData(
    val locationId: String = "",
    val areaName: String = "Chưa xác định",
    val status: String = "THONG THOANG (NORMAL)",
    val roiCount: String = "0",
    val stuckCount: String = "0",
    val timestamp: Long = 0L
)

object TrafficRepository {
    // Biến lưu độ chênh lệch thời gian giữa Client và Firebase Server (ms)
    private var serverTimeOffset: Long = 0L
    // Danh sách toàn bộ camera từ Firebase
    private val _camerasState = MutableStateFlow<List<CameraTrafficData>>(emptyList())
    val camerasState: StateFlow<List<CameraTrafficData>> = _camerasState.asStateFlow()

    // Camera đang chọn hiển thị chi tiết
    private val _selectedCameraId = MutableStateFlow<String?>(null)
    val selectedCameraId: StateFlow<String?> = _selectedCameraId.asStateFlow()

    // Danh sách các ID Camera được người dùng TOCK chọn nhận thông báo
    private val _selectedAlertCameraIds = MutableStateFlow<Set<String>>(emptySet())
    val selectedAlertCameraIds: StateFlow<Set<String>> = _selectedAlertCameraIds.asStateFlow()

    // Quản lý trạng thái ON / OFF tổng của Switch Slider
    private val _isAlertEnabled = MutableStateFlow(true)
    val isAlertEnabled: StateFlow<Boolean> = _isAlertEnabled.asStateFlow()

    private const val PREFS_NAME = "traffic_app_prefs"
    private const val KEY_ALERT_ENABLED = "key_alert_enabled"
    private const val KEY_SELECTED_CAMERAS = "key_selected_cameras"

    fun initRepository(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val isEnabled = prefs.getBoolean(KEY_ALERT_ENABLED, true)
        val savedSelectedCams = prefs.getStringSet(KEY_SELECTED_CAMERAS, emptySet()) ?: emptySet()

        _isAlertEnabled.value = isEnabled
        _selectedAlertCameraIds.value = savedSelectedCams

        if (isEnabled) subscribeToTopic() else unsubscribeFromTopic()

        val firebaseInstance = FirebaseDatabase.getInstance(BuildConfig.FIREBASE_DB_URL)

        // Lắng nghe sự thay đổi về độ chênh lệch giờ giữa Client và Firebase Server
        val offsetRef = firebaseInstance.getReference(".info/serverTimeOffset")
        offsetRef.addValueEventListener(object : ValueEventListener {
            override fun onDataChange(snapshot: DataSnapshot) {
                serverTimeOffset = snapshot.getValue(Long::class.java) ?: 0L
                Log.d("FirebaseDB", "Server time offset: $serverTimeOffset ms")
            }

            override fun onCancelled(error: DatabaseError) {
                Log.e("FirebaseDB", "Không thể lấy serverTimeOffset: ${error.message}")
            }
        })

        // Kết nối đến Realtime Database lắng nghe danh sách traffic_status
        val database = firebaseInstance.getReference("traffic_status")

        database.addValueEventListener(object : ValueEventListener {
            override fun onDataChange(snapshot: DataSnapshot) {
                // Thời gian hiện tại chuẩn theo Firebase Server
                val estimatedServerTime = System.currentTimeMillis() + serverTimeOffset
                val cameraList = mutableListOf<CameraTrafficData>()

                for (child in snapshot.children) {
                    val locId = child.child("location_id").getValue(String::class.java) ?: child.key ?: continue
                    val areaName = child.child("area_name").getValue(String::class.java) ?: "Ngã ba $locId"
                    val status = child.child("status").getValue(String::class.java) ?: "THONG THOANG (NORMAL)"
                    val roiCount = child.child("roi_count").getValue(String::class.java) ?: "0"
                    val stuckCount = child.child("stuck_count").getValue(String::class.java) ?: "0"
                    val timestamp = child.child("timestamp").getValue(Long::class.java) ?: estimatedServerTime

                    // LỌC MÁY CHỦ/CAMERA ĐANG HOẠT ĐỘNG: Nếu quá 15 giây không gửi heartbeat/data -> Cánh báo offline/Tự ẩn
                    if (estimatedServerTime - timestamp <= 15_000) {
                        cameraList.add(
                            CameraTrafficData(
                                locationId = locId,
                                areaName = areaName,
                                status = status,
                                roiCount = roiCount,
                                stuckCount = stuckCount,
                                timestamp = timestamp
                            )
                        )
                    }
                }

                _camerasState.value = cameraList

                // Nếu chưa chọn camera nào hoặc camera đã chọn bị ngắt kết nối -> Tự chọn camera đầu tiên
                if (_selectedCameraId.value == null || cameraList.none { it.locationId == _selectedCameraId.value }) {
                    _selectedCameraId.value = cameraList.firstOrNull()?.locationId
                }
            }

            override fun onCancelled(error: DatabaseError) {
                Log.e("FirebaseDB", "Lỗi tải DB: ${error.message}")
            }
        })
    }

    // Toggle tick cho từng Camera
    fun toggleCameraAlertSelection(context: Context, locationId: String) {
        val currentSet = _selectedAlertCameraIds.value.toMutableSet()
        if (currentSet.contains(locationId)) {
            currentSet.remove(locationId)
        } else {
            currentSet.add(locationId)
        }
        _selectedAlertCameraIds.value = currentSet

        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putStringSet(KEY_SELECTED_CAMERAS, currentSet).apply()
    }

    fun selectCamera(locationId: String) {
        _selectedCameraId.value = locationId
    }

    fun setAlertEnabled(context: Context, enabled: Boolean) {
        _isAlertEnabled.value = enabled
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putBoolean(KEY_ALERT_ENABLED, enabled).apply()

        if (enabled) subscribeToTopic() else unsubscribeFromTopic()
    }

    fun isAlertEnabledFromPrefs(context: Context): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getBoolean(KEY_ALERT_ENABLED, true)
    }

    fun isCameraSelectedFromPrefs(context: Context, locationId: String): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val selectedSet = prefs.getStringSet(KEY_SELECTED_CAMERAS, emptySet()) ?: emptySet()
        return selectedSet.contains(locationId)
    }

    private fun subscribeToTopic() {
        FirebaseMessaging.getInstance().subscribeToTopic("traffic_alerts")
    }

    private fun unsubscribeFromTopic() {
        FirebaseMessaging.getInstance().unsubscribeFromTopic("traffic_alerts")
    }
}