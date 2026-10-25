/**
 * App Config
 *
 * The fixed settings live in app.json; this adds what depends on the build:
 *
 * - The variant (APP_VARIANT, set per profile in eas.json): development, staging, or
 *   production. Each is a separate app with its own name, package, and URL scheme, so all
 *   three can be installed side by side and a sign-in always returns to the app that
 *   started it. Supabase must allow each scheme (memory-dev://**, memory-staging://**,
 *   memory://**). Unset (Expo Go, `npx expo start`): production's identity.
 * - Cleartext traffic: a build whose backend is plain http (the `local` profile, which
 *   talks to a backend on the home network) must allow it on Android; a build pointed at
 *   an https backend never does.
 * - A production or store build must point at an https backend.
 * - Push on Android: Firebase's google-services.json for these apps, stored in EAS as the
 *   secret file variable GOOGLE_SERVICES_JSON (its path on the build machine). Without it
 *   the app works and simply cannot receive push. See docs/DEPLOYMENT.md.
 */

import type { ConfigContext, ExpoConfig } from "expo/config";

type Variant = "development" | "staging" | "production";

const VARIANTS: Record<Variant, { name: string; id: string; scheme: string }> =
  {
    development: {
      name: "Zoop Dev",
      id: "com.museai.app.dev",
      scheme: "memory-dev",
    },
    staging: {
      name: "Zoop Staging",
      id: "com.museai.app.staging",
      scheme: "memory-staging",
    },
    production: { name: "Zoop", id: "com.museai.app", scheme: "memory" },
  };

function variantFromEnv(): Variant {
  const value = process.env.APP_VARIANT ?? "production";
  if (!(value in VARIANTS)) {
    throw new Error(
      `APP_VARIANT must be one of ${Object.keys(VARIANTS).join(", ")}.`,
    );
  }
  return value as Variant;
}

export default ({ config }: ConfigContext): ExpoConfig => {
  const variant = VARIANTS[variantFromEnv()];
  const googleServicesFile = process.env.GOOGLE_SERVICES_JSON;
  const apiUrl = process.env.EXPO_PUBLIC_API_URL ?? "";
  const profile = process.env.EAS_BUILD_PROFILE;
  // A store build must reach the hosted backend over https; without this it would build
  // fine and then fail on every request.
  if (
    (profile === "production" || profile === "store") &&
    !apiUrl.startsWith("https://")
  ) {
    throw new Error(
      "Production builds need EXPO_PUBLIC_API_URL set to the https address of the hosted " +
        "backend (in eas.json under the profile env, or as an EAS environment variable).",
    );
  }
  return {
    ...config,
    name: variant.name,
    slug: config.slug ?? "zoop",
    scheme: variant.scheme,
    ios: { ...config.ios, bundleIdentifier: variant.id },
    android: {
      ...config.android,
      package: variant.id,
      ...(googleServicesFile ? { googleServicesFile } : {}),
    },
    plugins: [
      ...(config.plugins ?? []),
      [
        "expo-build-properties",
        { android: { usesCleartextTraffic: apiUrl.startsWith("http://") } },
      ],
    ],
  };
};
