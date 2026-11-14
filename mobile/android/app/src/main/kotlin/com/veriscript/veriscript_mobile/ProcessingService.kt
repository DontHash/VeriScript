package com.veriscript.veriscript_mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * Keeps the app process alive while a long page job runs (docs/TECH_UPGRADE_PLAN.md, A3).
 *
 * Recognition, enhancement and export run in the app's own process. Without a
 * foreground service Android may kill that process as soon as the user
 * switches apps, stopping a 100-page batch half way. This service does no work
 * itself: it only holds a visible progress notification while Dart's work()
 * runs, and stops when the work ends. Drafts are still saved after every page,
 * so even if the system stops the app the finished pages are kept.
 */
class ProcessingService : Service() {
    companion object {
        private const val CHANNEL = "processing"
        private const val NOTIFICATION_ID = 41
        private const val EXTRA_TITLE = "title"
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_PERMILLE = "permille"

        @Volatile private var running = false

        fun start(context: Context, title: String, text: String, permille: Int) {
            val intent = Intent(context, ProcessingService::class.java)
                .putExtra(EXTRA_TITLE, title)
                .putExtra(EXTRA_TEXT, text)
                .putExtra(EXTRA_PERMILLE, permille)
            context.startForegroundService(intent)
        }

        fun update(context: Context, title: String, text: String, permille: Int) {
            if (!running) return
            context.getSystemService(NotificationManager::class.java)
                .notify(NOTIFICATION_ID, notification(context, title, text, permille))
        }

        fun stop(context: Context) {
            running = false
            context.stopService(Intent(context, ProcessingService::class.java))
        }

        private fun notification(context: Context, title: String, text: String, permille: Int): Notification {
            val manager = context.getSystemService(NotificationManager::class.java)
            if (manager.getNotificationChannel(CHANNEL) == null) {
                manager.createNotificationChannel(
                    NotificationChannel(CHANNEL, "Page processing", NotificationManager.IMPORTANCE_LOW).apply {
                        description = "Progress while pages are read or exported on this phone."
                        setShowBadge(false)
                    },
                )
            }
            val open = PendingIntent.getActivity(
                context, 0,
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val builder = Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_processing)
                .setContentTitle(title)
                .setContentText(text)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_PROGRESS)
                .setContentIntent(open)
                .setProgress(1000, permille.coerceIn(0, 1000), permille < 0)
            if (Build.VERSION.SDK_INT >= 31) {
                builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
            }
            return builder.build()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val title = intent?.getStringExtra(EXTRA_TITLE) ?: "VeriScript"
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "Working on your pages"
        val permille = intent?.getIntExtra(EXTRA_PERMILLE, -1) ?: -1
        val type = if (Build.VERSION.SDK_INT >= 35) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING
        } else {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        }
        try {
            startForeground(NOTIFICATION_ID, notification(this, title, text, permille), type)
            running = true
        } catch (e: Exception) {
            // Not allowed right now (e.g. started from the background): the
            // work continues without the guarantee; drafts are saved per page.
            running = false
            stopSelf()
        }
        return START_NOT_STICKY
    }

    /** API 35+: the system's time limit for this service type was reached. */
    override fun onTimeout(startId: Int, fgsType: Int) {
        running = false
        stopSelf()
    }

    override fun onDestroy() {
        running = false
        super.onDestroy()
    }
}
