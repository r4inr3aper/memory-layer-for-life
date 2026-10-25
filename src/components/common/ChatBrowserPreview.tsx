
import { Colors } from "@/constants/colors";
import { ChatBrowserPreviewData } from "@/types";

import * as WebBrowser from "expo-web-browser";
import {
    ActivityIndicator,
    StyleSheet,
    Text,
    TouchableOpacity,
    View,
} from "react-native";
import { WebView } from "react-native-webview";

type ChatBrowserPreviewProps = {
    browserPreview: ChatBrowserPreviewData;
};

const STATUS_TEXT: Record<ChatBrowserPreviewData["status"], string> = {
    running: "Starting the browser...",
    login_required: "The browser needs you to sign in.",
    completed: "Browser task finished.",
    failed: "Browser task failed.",
};

export function ChatBrowserPreview({
    browserPreview,
}: ChatBrowserPreviewProps) {
    const liveViewUrl = browserPreview.live_view_url;
    // The live view only works while the cloud browser session is open.
    const isLive =
        browserPreview.status === "running" ||
        browserPreview.status === "login_required";

    if (!liveViewUrl || !isLive) {
        return (
            <View style={[styles.browserPreview, styles.statusRow]}>
                {browserPreview.status === "running" ? (
                    <ActivityIndicator size="small" color={Colors.iconDark} />
                ) : null}
                <Text style={styles.statusText} numberOfLines={2}>
                    {STATUS_TEXT[browserPreview.status] ?? STATUS_TEXT.running}
                </Text>
            </View>
        );
    }

    return (
        <View style={styles.browserPreview}>
            <WebView
                source={{ uri: liveViewUrl }}
                style={styles.browserPreviewFrame}
                originWhitelist={["*"]}
                javaScriptEnabled
                domStorageEnabled
                startInLoadingState
                renderLoading={() => (
                    <View style={styles.browserPreviewLoading}>
                        <ActivityIndicator color={Colors.iconDark} />
                    </View>
                )}
            />

            <TouchableOpacity
                activeOpacity={0.85}
                style={styles.openBrowserButton}
                onPress={() => WebBrowser.openBrowserAsync(liveViewUrl)}>
                <Text style={styles.openBrowserButtonText}>
                    Open Browser
                </Text>
            </TouchableOpacity>
        </View>
    );
}

const styles = StyleSheet.create({
    browserPreview: {
        marginTop: 12,
        backgroundColor: Colors.browserPreviewBg,
        borderWidth: 1,
        borderColor: Colors.border,
        borderRadius: 16,
        overflow: "hidden",
    },
    browserPreviewFrame: {
        height: 220,
        backgroundColor: Colors.white,
        minWidth: 200
    },
    browserPreviewLoading: {
        position: "absolute",
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: Colors.white,
    },
    openBrowserButton: {
        marginHorizontal: 12,
        marginBottom: 12,
        height: 40,
        borderRadius: 20,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: Colors.iconDark,
    },
    openBrowserButtonText: {
        fontSize: 14,
        fontWeight: "700",
        color: Colors.white,
    },
    statusRow: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: 12,
        paddingVertical: 10,
    },
    statusText: {
        flexShrink: 1,
        fontSize: 13,
        fontWeight: "600",
        color: Colors.textSecondary,
    },
});
