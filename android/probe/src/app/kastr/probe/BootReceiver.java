package app.kastr.probe;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/**
 * Records that BOOT_COMPLETED reached the app (time + count). It never starts an activity or service: the probe only
 * needs to know whether a boot-time start would be possible for the real kiosk app.
 */
public final class BootReceiver extends BroadcastReceiver {

    static final String PREFS = "probe";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        p.edit()
            .putLong("boot_seen_at", System.currentTimeMillis())
            .putInt("boot_count", p.getInt("boot_count", 0) + 1)
            .apply();
    }
}
