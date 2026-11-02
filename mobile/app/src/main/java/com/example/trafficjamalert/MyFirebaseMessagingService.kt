package com.example.trafficjamalert

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class MyFirebaseMessagingService : FirebaseMessagingService() {

    companion object {
        private const val COOLDOWN_TIME_MS = 60_000L // Khoảng nghỉ 1 phút
        private const val PREFS_NAME = "fcm_cooldown_prefs"
    }

    private fun isCoolingDown(context: Context, locationId: String): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val lastTime = prefs.getLong("last_push_$locationId", 0L)
        val currentTime = System.currentTimeMillis()

        return (currentTime - lastTime) < COOLDOWN_TIME_MS
    }

    private fun updateLastPushTime(context: Context, locationId: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putLong("last_push_$locationId", System.currentTimeMillis()).apply()
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        // 1. Kiểm tra Switch tổng có ON không
        val isEnabled = TrafficRepository.isAlertEnabledFromPrefs(applicationContext)
        if (!isEnabled) {
            Log.d("FCM_APP", "App đang ở trạng thái OFF - Bỏ qua thông báo!")
            return
        }

        val locationId = remoteMessage.data["location_id"] ?: ""
        val status = remoteMessage.data["status"] ?: ""
        val title = remoteMessage.notification?.title ?: "⚠️ CẢNH BÁO TẮC NGHẼN"
        val body = remoteMessage.notification?.body ?: "Có khu vực bị tắc nghẽn!"

        // 2. Kiểm tra Camera cụ thể này có được TÍCK CHỌN nhận thông báo không
        val isCamSelected = TrafficRepository.isCameraSelectedFromPrefs(applicationContext, locationId)
        if (!isCamSelected) {
            Log.d("FCM_APP", "Camera [$locationId] không được tick nhận thông báo -> Bỏ qua.")
            return
        }

        // Kiểm tra thời gian Cooldown (1 phút) cho địa điểm này
        if (isCoolingDown(applicationContext, locationId)) {
            Log.d("FCM_APP", "Camera [$locationId] đang trong thời gian cooldown 1 phút -> Bỏ qua.")
            return
        }

        // 3. Nếu thỏa điều kiện & là TẮC NGHẼN -> Bật Push Notification
        if (status.contains("TAC NGHEN")) {
            showNotification(title, body)
            updateLastPushTime(applicationContext, locationId)
        }
    }

    private fun showNotification(title: String, body: String) {
        val channelId = "traffic_alert_channel"
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Cảnh Báo Tắc Nghẽn Giao Thông",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Kênh cảnh báo tắc nghẽn khẩn cấp"
                enableVibration(true)
            }
            notificationManager.createNotificationChannel(channel)
        }

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }

        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)

        notificationManager.notify(System.currentTimeMillis().toInt(), builder.build())
    }
}