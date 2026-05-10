# Deployment Checklist

## Backend

Deploy the Python backend separately from Google Play. Google Play only distributes the Android app; it does not host `server.py`.

Required production environment variables:

```bash
DATABASE_URL=${{Postgres.DATABASE_URL}}
APP_HOST=0.0.0.0
APP_PORT=${{PORT}}
FRONTEND_ORIGINS=capacitor://localhost,https://your-web-frontend.example
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=true
FIREBASE_CREDENTIALS_JSON={"type":"service_account",...}
```

Use a managed PostgreSQL database. On Railway, add a PostgreSQL service to the same project, then set `DATABASE_URL` from that service. On startup, `server.py` runs `init_db()` and creates the notification tables.

For scheduled price checks, run:

```bash
python run_checks.py --once
```

On Railway, configure this as a Cron service using the same code and database.
Use this cron schedule to check watched products every 3 hours:

```cron
0 */3 * * *
```

The Android app should read saved product data from the backend. If a live scrape is blocked, `/save` queues the product for this scheduled checker instead of requiring the user request to scrape immediately.

## Firebase

1. Create a Firebase project.
2. Add an Android app using package name `com.pricewatch.app`.
3. Download `google-services.json`.
4. Put it at `android/app/google-services.json` locally. This file is gitignored.
5. Create a Firebase service account JSON for the backend.
6. Store that JSON in Railway as `FIREBASE_CREDENTIALS_JSON`.

The Android app gets the FCM token. The backend stores it per user and sends notifications through Firebase Admin.

## Android

Build/sync web assets into Android:

```bash
npm run android:sync
```

Open Android Studio:

```bash
npm run android:open
```

Before building locally, install Android Studio/SDK and make sure `ANDROID_HOME` is set or `android/local.properties` contains:

```properties
sdk.dir=C:\\Users\\YOUR_USER\\AppData\\Local\\Android\\Sdk
```

For Google Play, build a signed Android App Bundle (`.aab`) from Android Studio.
