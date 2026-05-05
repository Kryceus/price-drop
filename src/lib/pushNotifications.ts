import { Capacitor } from "@capacitor/core";
import {
  PushNotifications,
  type Token,
} from "@capacitor/push-notifications";
import { notifications } from "@/lib/api";

const STORED_PUSH_TOKEN_KEY = "price_drop_push_token";

export type PushSetupResult =
  | { ok: true; token: string }
  | { ok: false; reason: string };

export function isNativePushAvailable() {
  return Capacitor.isNativePlatform();
}

export function hasStoredPushToken() {
  return Boolean(localStorage.getItem(STORED_PUSH_TOKEN_KEY));
}

export async function enablePushNotifications(): Promise<PushSetupResult> {
  if (!isNativePushAvailable()) {
    return { ok: false, reason: "Push notifications are available in the Android app." };
  }

  const permission = await PushNotifications.requestPermissions();
  if (permission.receive !== "granted") {
    return { ok: false, reason: "Notification permission was not granted." };
  }

  return new Promise<PushSetupResult>((resolve) => {
    let settled = false;

    const finish = (result: PushSetupResult) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    PushNotifications.addListener("registration", async (token: Token) => {
      try {
        localStorage.setItem(STORED_PUSH_TOKEN_KEY, token.value);
        await notifications.registerToken({
          token: token.value,
          platform: "android",
          device_label: navigator.userAgent,
        });
        finish({ ok: true, token: token.value });
      } catch (err) {
        finish({
          ok: false,
          reason: err instanceof Error ? err.message : "Could not register this device.",
        });
      }
    });

    PushNotifications.addListener("registrationError", (error) => {
      finish({
        ok: false,
        reason:
          typeof error.error === "string"
            ? error.error
            : "Could not register for push notifications.",
      });
    });

    PushNotifications.addListener("pushNotificationActionPerformed", () => {
      window.location.assign("/dashboard");
    });

    PushNotifications.register();
  });
}

export async function disableStoredPushToken() {
  const token = localStorage.getItem(STORED_PUSH_TOKEN_KEY);
  if (!token) return;

  try {
    await notifications.removeToken(token);
  } finally {
    localStorage.removeItem(STORED_PUSH_TOKEN_KEY);
  }
}
