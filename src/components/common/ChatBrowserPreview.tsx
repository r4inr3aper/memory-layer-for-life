/**
 * ChatBrowserPreview
 *
 * The cloud browser under an assistant message, as an iOS card: while the session is open,
 * its live view with an Open Browser button below it; otherwise one line of status.
 */

import { AppText, Button, Card } from "@/components/ui";
import { Colors } from "@/constants/colors";
import { ChatBrowserPreviewData } from "@/types";

import * as WebBrowser from "expo-web-browser";
import { ActivityIndicator, StyleSheet, View } from "react-native";
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
            <Card style={[styles.card, styles.statusRow]}>
                {browserPreview.status === "running" ? (
                    <ActivityIndicator
                        size="small"
                        color={Colors.secondaryLabel}
                    />
                ) : null}
                <AppText
                    variant="footnote"
                    color={
                        browserPreview.status === "failed"
                            ? "destructive"
                            : "secondary"
                    }
                    numberOfLines={2}
                    style={styles.statusText}
                >
                    {STATUS_TEXT[browserPreview.status] ?? STATUS_TEXT.running}
                </AppText>
            </Card>
        );
    }

    return (
        <Card style={[styles.card, styles.liveCard]}>
            <WebView
                source={{ uri: liveViewUrl }}
                style={styles.browserPreviewFrame}
                originWhitelist={["*"]}
                javaScriptEnabled
                domStorageEnabled
                startInLoadingState
                renderLoading={() => (
                    <View style={styles.browserPreviewLoading}>
                        <ActivityIndicator color={Colors.secondaryLabel} />
                    </View>
                )}
            />

            <View style={styles.footer}>
                <Button
                    title="Open Browser"
                    variant="tinted"
                    block
                    onPress={() => void WebBrowser.openBrowserAsync(liveViewUrl)}
                />
            </View>
        </Card>
    );
}

const styles = StyleSheet.create({
    card: {
        backgroundColor: Colors.groupedBackground,
    },
    liveCard: {
        padding: 0,
        overflow: "hidden",
    },
    browserPreviewFrame: {
        height: 220,
        backgroundColor: Colors.systemBackground,
    },
    browserPreviewLoading: {
        position: "absolute",
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: Colors.systemBackground,
    },
    footer: {
        padding: 12,
    },
    statusRow: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: 14,
        paddingVertical: 12,
    },
    statusText: {
        flexShrink: 1,
    },
});
