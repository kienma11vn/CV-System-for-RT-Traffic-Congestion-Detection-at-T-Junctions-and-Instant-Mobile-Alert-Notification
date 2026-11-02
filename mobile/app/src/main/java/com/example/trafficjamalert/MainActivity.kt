package com.example.trafficjamalert

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        if (!isGranted) {
            Toast.makeText(this, "Bạn cần bật quyền thông báo để nhận cảnh báo!", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        TrafficRepository.initRepository(applicationContext)
        askNotificationPermission()

        setContent {
            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = Color(0xFF1E272C)
                ) {
                    TrafficDashboardScreen()
                }
            }
        }
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }
}

fun formatTimestamp(timestamp: Long): String {
    if (timestamp == 0L) return "Chưa có dữ liệu"
    val sdf = SimpleDateFormat("HH:mm:ss - dd/MM/yyyy", Locale.getDefault())
    return sdf.format(Date(timestamp))
}

@Composable
fun TrafficDashboardScreen() {
    val context = LocalContext.current
    val cameras by TrafficRepository.camerasState.collectAsState()
    val selectedCameraId by TrafficRepository.selectedCameraId.collectAsState()
    val selectedAlertCameraIds by TrafficRepository.selectedAlertCameraIds.collectAsState()
    val isAlertEnabled by TrafficRepository.isAlertEnabled.collectAsState()

    // 1. Biến lưu từ khóa tìm kiếm
    var searchQuery by remember { mutableStateOf("") }

    // 2. Lọc danh sách camera theo tên khu vực (areaName) hoặc mã camera (locationId)
    val filteredCameras = remember(cameras, searchQuery) {
        if (searchQuery.isBlank()) {
            cameras
        } else {
            cameras.filter {
                it.areaName.contains(searchQuery, ignoreCase = true) ||
                        it.locationId.contains(searchQuery, ignoreCase = true)
            }
        }
    }

    // Tìm camera đang được chọn để hiển thị chi tiết bên dưới
    val activeCamera = cameras.find { it.locationId == selectedCameraId } ?: cameras.firstOrNull()

    val statusColor by animateColorAsState(
        targetValue = when {
            !isAlertEnabled -> Color(0xFF7F8C8D)
            activeCamera?.status?.contains("TAC NGHEN") == true -> Color(0xFFC0392B)
            activeCamera?.status?.contains("HEAVY") == true -> Color(0xFFD35400)
            else -> Color(0xFF27AE60)
        },
        label = "statusColor"
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "HỆ THỐNG THÔNG BÁO TẮC NGHẼN GIAO THÔNG",
            color = Color(0xFF00E676),
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(horizontal = 5.dp)
        )

        Spacer(modifier = Modifier.height(10.dp))

        // CARD BẬT / TẮT THÔNG BÁO TỔNG (SWITCH SLIDER)
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(containerColor = Color(0xFF2C3E50))
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = "Trạng thái nhận cảnh báo",
                        color = Color.White,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = if (isAlertEnabled) "Nhận thông báo camera đã chọn" else "Không nhận thông báo",
                        color = if (isAlertEnabled) Color(0xFF2ECC71) else Color(0xFFE74C3C),
                        fontSize = 12.sp
                    )
                }

                Switch(
                    checked = isAlertEnabled,
                    onCheckedChange = { TrafficRepository.setAlertEnabled(context, it) },
                    colors = SwitchDefaults.colors(
                        checkedThumbColor = Color.White,
                        checkedTrackColor = Color(0xFF2ECC71),
                        uncheckedThumbColor = Color.White,
                        uncheckedTrackColor = Color(0xFF7F8C8D)
                    )
                )
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        // ========================================================
        // SEARCH BAR TÌM KIẾM CAMERA THEO TÊN KHU VỰC
        // ========================================================
        OutlinedTextField(
            value = searchQuery,
            onValueChange = { searchQuery = it },
            placeholder = {
                Text("🔍 Tìm kiếm theo mã hoặc tên khu vực...", color = Color.Gray, fontSize = 12.sp)
            },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(10.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedContainerColor = Color(0xFF2C3E50),
                unfocusedContainerColor = Color(0xFF2C3E50),
                focusedBorderColor = Color(0xFF00E676),
                unfocusedBorderColor = Color(0xFF34495E),
                focusedTextColor = Color.White,
                unfocusedTextColor = Color.White
            )
        )

        Spacer(modifier = Modifier.height(10.dp))

        Text(
            text = "DANH SÁCH CAMERA HOẠT ĐỘNG (${filteredCameras.size})",
            color = Color(0xFFBDC3C7),
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.align(Alignment.Start)
        )

        Spacer(modifier = Modifier.height(6.dp))

        // DANH SÁCH DẠNG GRID CHỨA CÁC CAMERA ACTIVE (ĐÃ ĐƯỢC LỌC)
        if (filteredCameras.isEmpty()) {
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(100.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFF2C3E50))
            ) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        text = if (searchQuery.isNotEmpty()) "Không tìm thấy camera phù hợp..." else "Không có camera nào đang hoạt động...",
                        color = Color.Gray,
                        modifier = Modifier.padding(start = 15.dp)
                    )
                }
            }
        } else {
            LazyVerticalGrid(
                columns = GridCells.Fixed(2),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(180.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(filteredCameras) { camera ->
                    val isSelected = camera.locationId == activeCamera?.locationId
                    val isTicked = selectedAlertCameraIds.contains(camera.locationId)

                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { TrafficRepository.selectCamera(camera.locationId) },
                        shape = RoundedCornerShape(8.dp),
                        border = if (isSelected) BorderStroke(2.dp, Color(0xFF00E676)) else null,
                        colors = CardDefaults.cardColors(
                            containerColor = if (isSelected) Color(0xFF34495E) else Color(0xFF2C3E50)
                        )
                    ) {
                        Box(modifier = Modifier.padding(8.dp)) {
                            Column(modifier = Modifier.fillMaxWidth().padding(end = 24.dp)) {
                                Text(
                                    text = camera.areaName,
                                    color = Color.White,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                                Text(
                                    text = camera.locationId,
                                    color = Color(0xFFBDC3C7),
                                    fontSize = 11.sp
                                )
                                val (statusText, statusColor) = when {
                                    camera.status.contains("TAC NGHEN") -> "⚠️ Tắc nghẽn" to Color(0xFFE74C3C)
                                    camera.status.contains("HEAVY") || camera.status.contains("PHUONG TIEN DONG") -> "🟠 Nhiều xe" to Color(0xFFD35400)
                                    else -> "🟢 Thông thoáng" to Color(0xFF2ECC71)
                                }
                                Text(
                                    text = statusText,
                                    color = statusColor,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }

                            // TICK CHECKBOX GÓC TRÊN BÊN PHẢI CỦA Ô CAMERA
                            Checkbox(
                                checked = isTicked,
                                onCheckedChange = {
                                    TrafficRepository.toggleCameraAlertSelection(context, camera.locationId)
                                },
                                modifier = Modifier
                                    .align(Alignment.TopEnd)
                                    .size(20.dp),
                                colors = CheckboxDefaults.colors(
                                    checkedColor = Color(0xFF2ECC71),
                                    uncheckedColor = Color.Gray
                                )
                            )
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // KHU VỰC HIỂN THỊ CHI TIẾT CAMERA ĐƯỢC CHỌN
        if (activeCamera != null) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(containerColor = statusColor)
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "${activeCamera.areaName.uppercase()} (${activeCamera.locationId}): ",
                        color = Color.White,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = if (isAlertEnabled) activeCamera.status else "ĐÃ TẮT NHẬN DỮ LIỆU",
                        color = Color.White,
                        fontSize = 17.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // CHI TIẾT SỐ XE
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Card(
                    modifier = Modifier.weight(1f).padding(end = 4.dp),
                    shape = RoundedCornerShape(10.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF2C3E50))
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(text = "Số xe trong khu vực", color = Color(0xFFBDC3C7), fontSize = 11.sp)
                        Text(
                            text = if (isAlertEnabled) activeCamera.roiCount else "-",
                            color = Color(0xFF3498DB),
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }

                Card(
                    modifier = Modifier.weight(1f).padding(start = 4.dp),
                    shape = RoundedCornerShape(10.dp),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF2C3E50))
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(text = "Số xe bị kẹt", color = Color(0xFFBDC3C7), fontSize = 11.sp)
                        Text(
                            text = if (isAlertEnabled) activeCamera.stuckCount else "-",
                            color = Color(0xFFE74C3C),
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // THỜI GIAN CẬP NHẬT LẦN CUỐI
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(10.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFF34495E))
            ) {
                Column(
                    modifier = Modifier.padding(12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(text = "🕒 Cập nhật lần cuối:", color = Color(0xFFBDC3C7), fontSize = 11.sp)
                    Text(
                        text = if (isAlertEnabled && activeCamera.timestamp > 0) formatTimestamp(activeCamera.timestamp) else "Chưa nhận dữ liệu",
                        color = Color(0xFF1ABC9C),
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}