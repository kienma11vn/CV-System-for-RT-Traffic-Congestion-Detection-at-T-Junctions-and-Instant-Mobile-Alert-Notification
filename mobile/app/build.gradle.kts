import java.util.Properties

// Đọc thông số từ local.properties
val localProperties = Properties()
val localPropertiesFile = rootProject.file("local.properties")
if (localPropertiesFile.exists()) {
    localProperties.load(localPropertiesFile.inputStream())
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    id("com.google.gms.google-services")
}

android {
    namespace = "com.example.trafficjamalert"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.trafficjamalert"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
		// Tạo biến BuildConfig chứa Database URL
		val dbUrl = localProperties.getProperty("FIREBASE_DATABASE_URL") ?: ""
        buildConfigField("String", "FIREBASE_DB_URL", "\"$dbUrl\"")
    }
	
	buildFeatures {
        buildConfig = true // Bật tính năng BuildConfig
	}
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation(platform("androidx.compose:compose-bom:2023.08.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")

    // Firebase SDK
    implementation(platform("com.google.firebase:firebase-bom:34.16.0"))
    implementation("com.google.firebase:firebase-analytics")
    implementation("com.google.firebase:firebase-messaging-ktx:24.1.2")
    implementation("com.google.firebase:firebase-database")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}