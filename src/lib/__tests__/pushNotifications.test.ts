import { getMe, registerPushToken, unregisterPushToken } from "@/lib/api/me";
import {
    forgetPushRegistration,
    releasePushRegistration,
    syncPushRegistration,
} from "@/lib/pushNotifications";
import AsyncStorage from "@react-native-async-storage/async-storage";

jest.mock("@react-native-async-storage/async-storage", () =>
  jest.requireActual(
    "@react-native-async-storage/async-storage/jest/async-storage-mock",
  ),
);

jest.mock("@/lib/api/me", () => ({
  getMe: jest.fn(),
  registerPushToken: jest.fn(async () => undefined),
  unregisterPushToken: jest.fn(async () => undefined),
}));

jest.mock("@/lib/supabase", () => ({
  supabase: { auth: { onAuthStateChange: jest.fn() } },
}));

jest.mock("expo-constants", () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: "project-1" } } } },
}));

jest.mock("expo", () => ({ isRunningInExpoGo: jest.fn(() => false) }));

jest.mock("expo-device", () => ({ isDevice: true }));

// The real loader uses a dynamic import, which Jest cannot run; hand it the mock instead.
jest.mock("@/lib/notificationsModule", () => ({
  importNotifications: () =>
    Promise.resolve(jest.requireMock("expo-notifications")),
}));

jest.mock("expo-notifications", () => ({
  setNotificationHandler: jest.fn(),
  setNotificationChannelAsync: jest.fn(async () => null),
  AndroidImportance: { DEFAULT: 3 },
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(async () => ({
    data: "ExponentPushToken[abc]",
  })),
}));

const TOKEN_KEY = "zoop.pushToken";
const TOKEN = "ExponentPushToken[abc]";

const Notifications = jest.requireMock("expo-notifications");
const mockIsRunningInExpoGo = jest.requireMock("expo")
  .isRunningInExpoGo as jest.Mock;
const mockGetMe = getMe as jest.Mock;
const mockRegister = registerPushToken as jest.Mock;
const mockUnregister = unregisterPushToken as jest.Mock;

function permission(granted: boolean, canAskAgain = true) {
  return { granted, canAskAgain };
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockIsRunningInExpoGo.mockReturnValue(false);
  await AsyncStorage.clear();
});

describe("syncPushRegistration", () => {
  it("registers silently and remembers the token when permission was granted before", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue(permission(true));

    await syncPushRegistration();

    expect(mockRegister).toHaveBeenCalledWith(
      expect.objectContaining({ token: TOKEN }),
    );
    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(mockGetMe).not.toHaveBeenCalled();
    expect(await AsyncStorage.getItem(TOKEN_KEY)).toBe(TOKEN);
  });

  it("asks once when the user has notifications on and was never asked", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue(permission(false));
    Notifications.requestPermissionsAsync.mockResolvedValue(permission(true));
    mockGetMe.mockResolvedValue({ notifications_enabled: true });

    await syncPushRegistration();

    expect(Notifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(mockRegister).toHaveBeenCalledWith(
      expect.objectContaining({ token: TOKEN }),
    );
  });

  it("does not ask a user who turned notifications off", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue(permission(false));
    mockGetMe.mockResolvedValue({ notifications_enabled: false });

    await syncPushRegistration();

    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it("registers even with notifications off once permission exists, to take the token over", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue(permission(true));
    mockGetMe.mockResolvedValue({ notifications_enabled: false });

    await syncPushRegistration();

    expect(mockRegister).toHaveBeenCalledTimes(1);
  });

  it("never asks again after the user said no", async () => {
    Notifications.getPermissionsAsync.mockResolvedValue(
      permission(false, false),
    );

    await syncPushRegistration();

    expect(mockGetMe).not.toHaveBeenCalled();
    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it("does nothing in Expo Go", async () => {
    mockIsRunningInExpoGo.mockReturnValue(true);

    await syncPushRegistration();

    expect(Notifications.getPermissionsAsync).not.toHaveBeenCalled();
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it("never throws, so a failure cannot break sign-in", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    Notifications.getPermissionsAsync.mockResolvedValue(permission(true));
    mockRegister.mockRejectedValueOnce(new Error("offline"));

    await expect(syncPushRegistration()).resolves.toBeUndefined();

    expect(await AsyncStorage.getItem(TOKEN_KEY)).toBeNull();
    warn.mockRestore();
  });
});

describe("releasePushRegistration", () => {
  it("unregisters the token this device registered, then forgets it", async () => {
    await AsyncStorage.setItem(TOKEN_KEY, TOKEN);

    await releasePushRegistration();

    expect(mockUnregister).toHaveBeenCalledWith(TOKEN, expect.any(AbortSignal));
    expect(await AsyncStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("does nothing when this device never registered", async () => {
    await releasePushRegistration();

    expect(mockUnregister).not.toHaveBeenCalled();
  });

  it("still forgets the token when the server cannot be reached", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    await AsyncStorage.setItem(TOKEN_KEY, TOKEN);
    mockUnregister.mockRejectedValueOnce(new Error("offline"));

    await expect(releasePushRegistration()).resolves.toBeUndefined();

    expect(await AsyncStorage.getItem(TOKEN_KEY)).toBeNull();
    warn.mockRestore();
  });
});

describe("forgetPushRegistration", () => {
  it("forgets the token without calling the backend", async () => {
    await AsyncStorage.setItem(TOKEN_KEY, TOKEN);

    await forgetPushRegistration();

    expect(mockUnregister).not.toHaveBeenCalled();
    expect(await AsyncStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});
